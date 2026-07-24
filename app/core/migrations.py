"""Versioned, forward-only SQL migrations for the app-owned state schema.

Replaces the ad-hoc ``CREATE TABLE IF NOT EXISTS`` bootstrap that used to live
in ``core.state``. Migrations are numbered SQL files under ``migrations/versions/``
(``NNNN__description.sql``); each is applied at most once, in order, and tracked
in a ``schema_migrations`` table in the app-owned schema.

This runner is intentionally dependency-free (plain psycopg over the existing
app pool, which already pins ``search_path`` to the app schema) so it works both
at app startup AND headless in CI. It aligns with the file layout of the
lakebase-app-dev-kit, which the team can graduate to for paired git/Lakebase
branching, schema diffing and rollback.

Scope: the app-owned state schema ONLY. The read-only synced KPI aggregates are
never touched here.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from core.config import Cyber360Config
from core.db import get_pool

logger = logging.getLogger(__name__)

# migrations/versions/ lives next to the app package (app/migrations/versions).
_VERSIONS_DIR = Path(__file__).parent.parent / "migrations" / "versions"
_FILENAME_RE = re.compile(r"^(\d{4})__.+\.sql$")


def _discover() -> list[tuple[str, Path]]:
    """Return (version, path) for every valid migration file, sorted by version."""
    if not _VERSIONS_DIR.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for path in _VERSIONS_DIR.iterdir():
        m = _FILENAME_RE.match(path.name)
        if m:
            found.append((m.group(1), path))
    found.sort(key=lambda vp: vp[0])
    return found


async def run_migrations(config: Cyber360Config) -> None:
    """Apply every pending migration, in order, exactly once.

    Idempotent: already-applied versions (recorded in ``schema_migrations``) are
    skipped. Safe to run on every startup and in CI. Never raises for a healthy
    already-migrated database; a failing migration aborts the run and re-raises
    so the failure is visible.
    """
    if not config.lakebase.enabled:
        return
    pool = get_pool()
    if pool is None:
        logger.info("No Lakebase pool -- skipping migrations")
        return

    migrations = _discover()
    if not migrations:
        logger.warning("No migration files found under %s", _VERSIONS_DIR)
        return

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            # Tracking table lives in the app schema (search_path pinned by pool).
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version     TEXT PRIMARY KEY,
                    filename    TEXT NOT NULL,
                    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            await conn.commit()

            await cur.execute("SELECT version FROM schema_migrations")
            applied = {row[0] for row in await cur.fetchall()}

            pending = [(v, p) for v, p in migrations if v not in applied]
            if not pending:
                logger.info("Migrations up to date (%d applied)", len(applied))
                return

            for version, path in pending:
                sql = path.read_text()
                logger.info("Applying migration %s (%s)", version, path.name)
                try:
                    await cur.execute(sql)
                    await cur.execute(
                        "INSERT INTO schema_migrations (version, filename) VALUES (%s, %s)",
                        (version, path.name),
                    )
                    await conn.commit()
                except Exception:
                    await conn.rollback()
                    logger.exception("Migration %s failed -- aborting", version)
                    raise

    logger.info("Applied %d migration(s)", len(pending))
