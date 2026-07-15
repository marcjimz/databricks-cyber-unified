"""Lakebase (managed Postgres) connectivity.

Lakebase is accessed as the app SERVICE PRINCIPAL, never per-user OBO. The
Lakebase instance is bound to the app as a resource in databricks.yml, so the
control plane (a) grants the SP CAN_CONNECT_AND_CREATE and (b) injects
PGHOST / PGUSER / PGPORT / PGDATABASE into the runtime. Both access modes below
mint their token with a bare ``WorkspaceClient()`` (ambient SP OAuth):

  * App-level pool -- app-owned STATE tables (preferences / chats / sessions)
    that the session-bootstrap migrations create and maintain. Opened at startup.

  * Per-request connection -- the read-only KPI aggregate reads.

Interactive Genie / SQL Warehouse access (elsewhere) stays OBO; only the
Lakebase Postgres connection is SP-based. Everything is gracefully disabled
when Lakebase is not configured, so the seed provider keeps working with zero
workspace dependencies.
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    import psycopg
    from psycopg_pool import AsyncConnectionPool

    from core.config import Cyber360Config

logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None


# ---------------------------------------------------------------------------
# Credential + DSN helpers
# ---------------------------------------------------------------------------

def _lakebase_dsn(config: Cyber360Config, password: str, *, search_path: str = "") -> str:
    """Build a psycopg conninfo string for the Lakebase instance.

    Host / user / port / dbname come from the PG* env vars the control plane
    injects when the Lakebase instance is bound as an app resource. Falls back
    to config-derived values for local/dev where the binding is absent.

    ``search_path`` pins the session schema resolution as a libpq connection
    *option* (session-level, not transactional -- so it survives the connection
    pool's between-checkout reset, unlike a ``SET`` statement). The two access
    paths use different schemas: the app-level pool points at the SP-owned state
    schema, while per-request reads point at the read-only synced-aggregate
    schema.
    """
    host = os.environ.get("PGHOST") or os.environ.get("LAKEBASE_HOST", "")
    port = os.environ.get("PGPORT", "5432")
    dbname = os.environ.get("PGDATABASE") or config.lakebase.database_name
    user = os.environ.get("PGUSER", "")
    dsn = (
        f"host={host} port={port} dbname={dbname} "
        f"user={user} password={password} sslmode=require"
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
    cred = ws.database.generate_database_credential(
        request_id=str(uuid.uuid4()),
        instance_names=[config.lakebase.instance_name],
    )
    return cred.token


# ---------------------------------------------------------------------------
# App-level pool (state tables)
# ---------------------------------------------------------------------------

async def init_lakebase_pool(config: Cyber360Config) -> None:
    """Open the app-level connection pool if Lakebase is enabled."""
    global _pool

    if not config.lakebase.enabled or not config.lakebase.instance_name:
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


# ---------------------------------------------------------------------------
# Per-request connection (KPI aggregate reads) -- app service principal
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lakebase_connection(
    config: Cyber360Config,
) -> AsyncIterator[psycopg.AsyncConnection]:
    """Yield a short-lived Lakebase connection authenticated as the app SP.

    KPI aggregate reads run as the service principal (not per-user OBO). Raises
    PermissionError when the credential mint or connection is rejected, which the
    API layer surfaces as HTTP 403 (access restricted).
    """
    import psycopg

    try:
        # Synced aggregates land in the UC/Postgres schema named by
        # data_source.schema (dev-mode prefixes it, e.g. dev_<user>_posture).
        # The SP has USAGE + SELECT there; pin search_path so the provider's
        # unqualified reads resolve to it.
        dsn = _lakebase_dsn(
            config, _sp_credential(config), search_path=config.data_source.schema_
        )
    except Exception as exc:  # credential mint failed -> treat as access denied
        raise PermissionError(f"Unable to obtain Lakebase credential: {exc}") from exc

    conn = None
    try:
        conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        yield conn
    except psycopg.OperationalError as exc:
        raise PermissionError(f"Lakebase connection refused: {exc}") from exc
    finally:
        if conn is not None:
            await conn.close()
