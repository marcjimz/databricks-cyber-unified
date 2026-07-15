"""FastAPI dependency injection providers.

Provides access to the loaded config, SQL client, Lakebase pool,
and OBO token via FastAPI's Depends() mechanism.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from core.config import Cyber360Config
from core.sql import SQLClient

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

# Module-level singletons set during app lifespan
_config: Cyber360Config | None = None
_sql_client: SQLClient | None = None


def set_global_config(config: Cyber360Config) -> None:
    """Set the global config instance during app startup."""
    global _config, _sql_client
    _config = config
    if config.data_source.warehouse_id:
        _sql_client = SQLClient(warehouse_id=config.data_source.warehouse_id)


def get_config() -> Cyber360Config:
    """FastAPI dependency: returns the loaded Cyber360 config."""
    assert _config is not None, "Config not loaded -- app lifespan not started"
    return _config


def get_sql_client() -> SQLClient | None:
    """FastAPI dependency: returns the SQL Warehouse client (may be None if no warehouse configured)."""
    return _sql_client


def get_obo_token(request: Request) -> str:
    """FastAPI dependency: returns the OBO token from request state."""
    return getattr(request.state, "obo_token", "")


def get_user_email(request: Request) -> str:
    """FastAPI dependency: returns the user email from request state."""
    return getattr(request.state, "user_email", "unknown")


def get_lakebase_pool() -> AsyncConnectionPool | None:
    """FastAPI dependency: returns the Lakebase connection pool."""
    from core.db import get_pool
    return get_pool()
