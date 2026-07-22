"""Lakebase (managed Postgres) connectivity.

Lakebase is accessed as the app SERVICE PRINCIPAL, never per-user OBO. The
Lakebase autoscaling branch is bound to the app as a ``postgres`` resource in
databricks.yml, which grants the SP CAN_CONNECT_AND_CREATE on the branch. Unlike
the legacy ``database`` binding, the autoscaling binding does NOT auto-inject
PGHOST / PGUSER / PGPORT / PGDATABASE -- the app self-configures from
LAKEBASE_ENDPOINT_NAME: the host is resolved via ``postgres.get_endpoint`` and
the SP username from DATABRICKS_CLIENT_ID. Both access modes below mint their
token with a bare ``WorkspaceClient()`` (ambient SP OAuth):

  * App-level pool -- app-owned STATE tables (preferences / chats / sessions)
    that the session-bootstrap migrations create and maintain. Opened at
    startup. Connects as the SP's own Postgres role (it owns this schema).

  * Per-request connection -- the read-only KPI aggregate reads. Connects with
    PGUSER = a Databricks *group* role (``lakebase.reader_role``) that holds the
    USAGE + SELECT grants on the synced schema; the SP is a group member, so its
    token authenticates and the session runs as the group role. This centralizes
    the read grant on the group instead of per-SP object grants.

Interactive Genie / SQL Warehouse access (elsewhere) stays OBO; only the
Lakebase Postgres connection is SP-based. Everything is gracefully disabled
when Lakebase is not configured, so the seed provider keeps working with zero
workspace dependencies.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    import psycopg
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
    user: str = "",
) -> str:
    """Build a psycopg conninfo string for the Lakebase endpoint.

    Host is resolved from the bound endpoint (``_resolve_host``). The Postgres
    username defaults to the SP's DATABRICKS_CLIENT_ID (Lakebase authenticates
    the SP as a Postgres role named for its client id), but an explicit ``user``
    override takes precedence -- used by the KPI read path to connect AS a
    Databricks group role (the SP is a member, so its own OAuth token still
    authenticates, and the session runs as the group role). PGUSER / PGPORT /
    PGDATABASE env vars override for local/dev.

    ``search_path`` pins the session schema resolution as a libpq connection
    *option* (session-level, not transactional -- so it survives the connection
    pool's between-checkout reset, unlike a ``SET`` statement). The two access
    paths use different schemas: the app-level pool points at the SP-owned state
    schema, while per-request reads point at the read-only synced-aggregate
    schema.
    """
    host = _resolve_host(config)
    port = os.environ.get("PGPORT", "5432")
    dbname = os.environ.get("PGDATABASE") or config.lakebase.database_name
    pg_user = user or os.environ.get("PGUSER") or os.environ.get("DATABRICKS_CLIENT_ID", "")
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


# ---------------------------------------------------------------------------
# Per-request connection (KPI aggregate reads) -- app service principal
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lakebase_connection(
    config: Cyber360Config,
) -> AsyncIterator[psycopg.AsyncConnection]:
    """Yield a short-lived Lakebase connection for the KPI aggregate reads.

    The SP's OAuth token always authenticates the connection (not per-user OBO).
    When ``lakebase.reader_role`` is set, the connection's PGUSER is that
    Databricks group role instead of the SP's own role: the SP is a group
    member, so its token is accepted and the session runs AS the group role,
    inheriting the group's USAGE + SELECT on the synced schema. When unset, it
    connects as the SP's own Postgres role (which then needs a direct grant).

    Raises PermissionError when the credential mint or connection is rejected,
    which the API layer surfaces as HTTP 403 (access restricted).
    """
    import psycopg

    try:
        # Synced aggregates land in the UC/Postgres schema named by
        # data_source.schema (dev-mode prefixes it, e.g. dev_<user>_posture).
        # The group reader role has USAGE + SELECT there; pin search_path so the
        # provider's unqualified reads resolve to it.
        dsn = _lakebase_dsn(
            config,
            _sp_credential(config),
            search_path=config.data_source.schema_,
            user=config.lakebase.reader_role,
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
