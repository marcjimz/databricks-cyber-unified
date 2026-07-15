"""App-owned state: idempotent session-bootstrap migrations.

The app owns three read-write state tables in Lakebase, entirely separate
from the read-only synced KPI aggregates:

    cyber360_preferences  -- per-user UI preferences (theme, reporting period)
    cyber360_chats        -- Genie chat history
    cyber360_sessions     -- lightweight session records

These are created with ``CREATE TABLE IF NOT EXISTS`` at startup so the app
bootstraps its own schema without a separate migration tool. The synced
aggregate tables are never touched here.
"""

from __future__ import annotations

import logging

from core.config import Cyber360Config
from core.db import get_pool

logger = logging.getLogger(__name__)


def _ddl(config: Cyber360Config) -> list[str]:
    t = config.lakebase.state_tables
    app_schema = config.lakebase.app_schema
    return [
        # The app SP owns its state schema (it has database-level CREATE from the
        # bound Lakebase resource). The pool pins search_path to this schema, so
        # the unqualified CREATE TABLEs below land here.
        f'CREATE SCHEMA IF NOT EXISTS "{app_schema}"',
        f"""
        CREATE TABLE IF NOT EXISTS {t.preferences} (
            user_email        TEXT PRIMARY KEY,
            theme             TEXT NOT NULL DEFAULT 'light',
            reporting_period  INTEGER NOT NULL DEFAULT 30,
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {t.chats} (
            chat_id     TEXT PRIMARY KEY,
            user_email  TEXT NOT NULL,
            domain      TEXT,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {t.sessions} (
            session_id  TEXT PRIMARY KEY,
            user_email  TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        f"CREATE INDEX IF NOT EXISTS idx_{t.chats}_user ON {t.chats} (user_email, created_at)",
        f"CREATE INDEX IF NOT EXISTS idx_{t.sessions}_user ON {t.sessions} (user_email)",
    ]


async def run_state_migrations(config: Cyber360Config) -> None:
    """Create the app-owned state tables if they do not already exist."""
    if not config.lakebase.enabled:
        return
    pool = get_pool()
    if pool is None:
        logger.info("No Lakebase pool -- skipping state migrations")
        return
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                for stmt in _ddl(config):
                    await cur.execute(stmt)
            await conn.commit()
        logger.info("Lakebase state tables ready (preferences/chats/sessions)")
    except Exception:
        logger.exception("State migrations failed -- app state persistence unavailable")
