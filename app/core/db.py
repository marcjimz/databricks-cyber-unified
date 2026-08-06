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

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from core.config import Cyber360Config

logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None

# Endpoint host is stable for the life of the endpoint, so resolve it once via
# the SDK and cache it -- the per-request DSN build must not pay a control-plane
# round-trip on every connection.
_pghost: str | None = None


# ---------------------------------------------------------------------------
# Credential + DSN helpers
# ---------------------------------------------------------------------------

def _resolve_host(config: Cyber360Config) -> str:
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
    config: Cyber360Config,
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


def _sp_credential(config: Cyber360Config) -> str:
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

async def init_lakebase_pool(config: Cyber360Config) -> None:
    """Open the app-level connection pool if Lakebase is enabled."""
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
        _pool = AsyncConnectionPool(conninfo=dsn, min_size=1, max_size=5, open=False)
        await _pool.open()
        logger.info("Lakebase app-level connection pool initialized")
    except Exception:
        logger.exception("Failed to initialize Lakebase pool -- continuing without persistence")
        _pool = None


async def close_lakebase_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> AsyncConnectionPool | None:
    return _pool
