"""Lakebase (managed Postgres) connectivity -- app-owned STATE only.

Lakebase now serves a single role: the app-owned read-write state tables
(preferences / chats / sessions) that the session-bootstrap migrations create
and maintain. KPI reads moved to native UC metric-view queries on the SQL
Warehouse (see ``providers/metricview.py``), so there is no longer a Postgres
KPI read path here.

The app connects as its SERVICE PRINCIPAL via an app-level pool opened at
startup. The Lakebase autoscaling branch is bound to the app as a ``postgres``
resource in databricks.yml (CAN_CONNECT_AND_CREATE). That binding does not
inject PGHOST/PGUSER/PGPORT/PGDATABASE, so the app self-configures from
LAKEBASE_ENDPOINT_NAME: the host is resolved via ``postgres.get_endpoint`` and
the SP username from DATABRICKS_CLIENT_ID, with the token minted from a bare
``WorkspaceClient()`` (ambient SP OAuth). Everything is gracefully disabled when
Lakebase is not configured, so the seed provider keeps working with zero
workspace dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from core.config import CyberUnifiedConfig

logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None

# How long a single pool checkout waits before raising. Bounded so a still-waking
# (scale-to-zero) endpoint surfaces an error instead of hanging a request forever.
_POOL_CHECKOUT_TIMEOUT = 30.0

# Background warm-up: keep retrying the first connection until the endpoint
# finishes its cold start. CONNECTING is what wakes Lakebase, so this is the wake
# trigger -- it just runs OFF the startup path so the health check is never blocked.
_WARMUP_ATTEMPTS = 12
_WARMUP_BACKOFF = 10.0
_warmup_task: asyncio.Task | None = None

# Endpoint host is stable for the life of the endpoint, so resolve it once via
# the SDK and cache it -- the per-request DSN build must not pay a control-plane
# round-trip on every connection.
_pghost: str | None = None


# ---------------------------------------------------------------------------
# Credential + DSN helpers
# ---------------------------------------------------------------------------

def _resolve_host(config: CyberUnifiedConfig) -> str:
    """Resolve (and cache) the Lakebase Postgres host for the bound endpoint.

    The autoscaling ``postgres`` app binding does not inject PGHOST, so the host
    is looked up from the endpoint path via ``postgres.get_endpoint``. A PGHOST
    env var (set for local dev) short-circuits the lookup.
    """
    global _pghost
    env_host = os.environ.get("PGHOST") or os.environ.get("LAKEBASE_HOST")
    if env_host:
        return env_host
    if _pghost:
        return _pghost

    from databricks.sdk import WorkspaceClient

    ws = WorkspaceClient()
    endpoint = ws.postgres.get_endpoint(name=config.lakebase.endpoint_name)
    _pghost = endpoint.status.hosts.host
    return _pghost


def _lakebase_dsn(
    config: CyberUnifiedConfig,
    password: str,
    *,
    search_path: str = "",
) -> str:
    """Build a psycopg conninfo string for the Lakebase endpoint (app SP).

    Host is resolved from the bound endpoint (``_resolve_host``); the Postgres
    username is the SP's DATABRICKS_CLIENT_ID (Lakebase authenticates the SP as a
    Postgres role named for its client id). PGUSER / PGPORT / PGDATABASE env vars
    override for local/dev.

    ``search_path`` pins the session schema resolution as a libpq connection
    *option* (session-level, so it survives the pool's between-checkout reset,
    unlike a ``SET`` statement) -- the app-level pool points it at the SP-owned
    state schema.
    """
    host = _resolve_host(config)
    port = os.environ.get("PGPORT", "5432")
    dbname = os.environ.get("PGDATABASE") or config.lakebase.database_name
    pg_user = os.environ.get("PGUSER") or os.environ.get("DATABRICKS_CLIENT_ID", "")
    dsn = (
        f"host={host} port={port} dbname={dbname} "
        f"user={pg_user} password={password} sslmode=require"
    )
    if search_path:
        # Schema names here are simple identifiers, so no inner quoting needed.
        dsn += f" options='-c search_path={search_path},public'"
    return dsn


def _sp_credential(config: CyberUnifiedConfig) -> str:
    """Mint a Lakebase token as the app SERVICE PRINCIPAL.

    A bare ``WorkspaceClient()`` authenticates with the app's ambient OAuth env
    (the SP), which is what the bound Lakebase resource authorizes. This also
    avoids the "more than one authorization method configured: oauth and pat"
    conflict that mixing a user token into the SDK would trigger.
    """
    from databricks.sdk import WorkspaceClient

    ws = WorkspaceClient()
    cred = ws.postgres.generate_database_credential(
        endpoint=config.lakebase.endpoint_name,
    )
    return cred.token


# ---------------------------------------------------------------------------
# App-level pool (state tables)
# ---------------------------------------------------------------------------

async def init_lakebase_pool(config: CyberUnifiedConfig) -> None:
    """Open the app-level connection pool if Lakebase is enabled.

    MUST NOT BLOCK APP STARTUP. Lakebase scales to zero (see
    var.lakebase_suspend_after), and CONNECTING is what wakes it -- but that cold
    start takes tens of seconds, longer than the Databricks Apps startup health
    check. Previously this opened the pool with ``min_size=1`` and no timeout, so a
    suspended endpoint made startup hang: ``Application startup complete`` never
    printed and the platform killed the app mid-wake, every time. Idle app + idle
    Lakebase meant every visit hit a double cold start and crashed.

    So the pool is created with ``min_size=0`` and a bounded connect timeout: no
    connection is demanded up front, and the first real checkout (or the
    background warm-up in ``start_lakebase_warmup``) triggers the wake.
    """
    global _pool

    if not config.lakebase.enabled or not config.lakebase.endpoint_name:
        logger.info("Lakebase disabled or not configured -- skipping pool init")
        return

    try:
        from psycopg_pool import AsyncConnectionPool

        # State tables live in the SP-owned app schema; pin search_path there so
        # the session-bootstrap DDL and all state reads/writes resolve to it.
        dsn = _lakebase_dsn(
            config, _sp_credential(config), search_path=config.lakebase.app_schema
        )
        # min_size=0: never block on a connection at creation time. timeout bounds
        # how long a single checkout waits, so a still-waking endpoint raises
        # (caught by callers) instead of hanging forever.
        _pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=0,
            max_size=5,
            timeout=_POOL_CHECKOUT_TIMEOUT,
            open=False,
        )
        await _pool.open()
        logger.info("Lakebase pool created (lazy, schema=%s)", config.lakebase.app_schema)
    except Exception:
        logger.exception("Failed to create Lakebase pool -- continuing without persistence")
        _pool = None


async def ensure_app_schema(config: CyberUnifiedConfig) -> None:
    """Create the SP-owned app schema. Requires a live connection (wakes Lakebase).

    On a fresh Lakebase database only ``public`` exists (and the SP is not its
    owner), so ``search_path=<app_schema>,public`` would otherwise fall through to
    ``public`` and the migration DDL fails with "permission denied for schema
    public". The SP holds database-level CREATE (CAN_CONNECT_AND_CREATE), so it can
    create + own this schema itself -- no external grant needed.
    """
    if _pool is None:
        return
    app_schema = config.lakebase.app_schema
    async with _pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{app_schema}"')
        await conn.commit()
    logger.info("Lakebase app schema ready (schema=%s)", app_schema)


async def _warmup(config: CyberUnifiedConfig) -> None:
    """Wake Lakebase and bootstrap state, retrying through the cold start.

    Runs as a BACKGROUND task so app startup never waits on it. Opening a
    connection is what wakes a scale-to-zero endpoint, so this is the wake trigger
    -- it just keeps retrying until the endpoint finishes coming up, then creates
    the app schema and applies the state migrations.

    Every failure path is swallowed: Lakebase holds only app state
    (preferences/chats/sessions), and KPI reads go to the SQL warehouse, so the app
    must stay fully usable even if this never succeeds.
    """
    # Imported here to avoid a circular import (migrations imports get_pool).
    from core.migrations import run_migrations

    for attempt in range(1, _WARMUP_ATTEMPTS + 1):
        try:
            await ensure_app_schema(config)
            await run_migrations(config)
            logger.info("Lakebase ready (state persistence enabled)")
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info(
                "Lakebase not ready yet (attempt %d/%d): %s -- retrying in %.0fs",
                attempt, _WARMUP_ATTEMPTS, exc, _WARMUP_BACKOFF,
            )
            await asyncio.sleep(_WARMUP_BACKOFF)

    logger.warning(
        "Lakebase did not become ready after %d attempts -- running without "
        "persistence (KPIs are unaffected; they read the SQL warehouse)",
        _WARMUP_ATTEMPTS,
    )


def start_lakebase_warmup(config: CyberUnifiedConfig) -> None:
    """Kick off the background Lakebase warm-up. Returns immediately."""
    global _warmup_task
    if _pool is None:
        return
    _warmup_task = asyncio.create_task(_warmup(config))


async def stop_lakebase_warmup() -> None:
    """Cancel the warm-up task if it is still retrying (shutdown path)."""
    global _warmup_task
    if _warmup_task and not _warmup_task.done():
        _warmup_task.cancel()
        try:
            await _warmup_task
        except (asyncio.CancelledError, Exception):
            pass
    _warmup_task = None


async def close_lakebase_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> AsyncConnectionPool | None:
    return _pool
