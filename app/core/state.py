"""App-owned state bootstrap.

The app owns three read-write state tables in Lakebase, entirely separate from
the read-only synced KPI aggregates:

    cyber_unified_preferences  -- per-user UI preferences (theme, reporting period)
    cyber_unified_chats        -- Genie chat history
    cyber_unified_sessions     -- lightweight session records

Their schema is now defined as **versioned SQL migrations** under
``migrations/versions/`` and applied by ``core.migrations.run_migrations`` (the
DDL formerly inlined here moved to ``0001__initial_state_tables.sql``). This
module keeps the ``run_state_migrations`` entry point so the app lifespan hook
is unchanged; it simply delegates to the migration runner.
"""

from __future__ import annotations

from core.config import CyberUnifiedConfig
from core.migrations import run_migrations


async def run_state_migrations(config: CyberUnifiedConfig) -> None:
    """Apply the app-owned state migrations (delegates to the migration runner)."""
    await run_migrations(config)
