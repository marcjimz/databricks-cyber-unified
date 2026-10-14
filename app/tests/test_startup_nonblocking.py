"""App startup must never block on Lakebase.

Lakebase scales to zero. Connecting is what WAKES it, but that cold start outlasts
the Databricks Apps startup health check -- so doing it inline left the app stuck on
"Waiting for application startup." until the platform killed it. These tests pin the
contract: the pool is lazy, the wake happens in the background, and the app is fully
serving before Lakebase is ready.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from core import db


def test_pool_is_created_lazily_with_a_bounded_timeout() -> None:
    """min_size=0 + a checkout timeout: no connection is demanded at startup.

    min_size>=1 makes pool creation wait for a live connection, which is exactly
    what hung startup against a suspended endpoint. No timeout means a checkout can
    hang a request forever.
    """
    source = inspect.getsource(db.init_lakebase_pool)
    assert "min_size=0" in source, (
        "pool must be created with min_size=0 so startup never waits for a "
        "connection to a scale-to-zero endpoint"
    )
    assert "timeout=_POOL_CHECKOUT_TIMEOUT" in source, (
        "pool must carry a bounded checkout timeout so a still-waking endpoint "
        "raises instead of hanging"
    )
    assert db._POOL_CHECKOUT_TIMEOUT > 0


def test_startup_does_not_await_the_wake() -> None:
    """The lifespan must call start_lakebase_warmup (sync, fire-and-forget).

    Awaiting the schema bootstrap / migrations inline is the regression: it put a
    Lakebase cold start on the startup path.
    """
    # Read main.py as TEXT rather than importing it -- fastapi is not installed in
    # every test environment, and this assertion is about the source contract.
    main_src = (Path(__file__).parent.parent / "main.py").read_text()
    start = main_src.index("async def lifespan")
    source = main_src[start:main_src.index("\napp = FastAPI", start)]

    assert "start_lakebase_warmup(config)" in source
    assert "await start_lakebase_warmup" not in source, (
        "the warm-up must NOT be awaited -- that reintroduces the blocking startup"
    )
    assert "await run_state_migrations" not in source, (
        "migrations must run in the background warm-up, not inline at startup"
    )
    # start_lakebase_warmup must be synchronous, so it cannot be accidentally awaited
    # into blocking behaviour.
    assert not inspect.iscoroutinefunction(db.start_lakebase_warmup)


def test_warmup_retries_through_a_cold_start(monkeypatch) -> None:
    """The warm-up keeps retrying until the endpoint finishes waking."""
    attempts = {"n": 0}

    async def flaky_schema(config):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OSError("connection timed out (endpoint still waking)")

    async def noop_migrations(config):
        return None

    monkeypatch.setattr(db, "ensure_app_schema", flaky_schema)
    monkeypatch.setattr("core.migrations.run_migrations", noop_migrations)
    monkeypatch.setattr(db, "_WARMUP_BACKOFF", 0.0)

    asyncio.run(db._warmup(config=object()))

    assert attempts["n"] == 3, f"expected retry until success, got {attempts['n']}"


def test_warmup_gives_up_without_crashing(monkeypatch) -> None:
    """If Lakebase never wakes, the app keeps running -- state is optional."""
    async def always_fails(config):
        raise OSError("endpoint unavailable")

    monkeypatch.setattr(db, "ensure_app_schema", always_fails)
    monkeypatch.setattr(db, "_WARMUP_BACKOFF", 0.0)
    monkeypatch.setattr(db, "_WARMUP_ATTEMPTS", 3)

    # Must NOT raise -- KPI reads go to the SQL warehouse and are unaffected.
    asyncio.run(db._warmup(config=object()))


def test_warmup_is_cancellable(monkeypatch) -> None:
    """Shutdown must be able to cancel a warm-up that is still retrying."""
    async def slow(config):
        await asyncio.sleep(10)

    monkeypatch.setattr(db, "ensure_app_schema", slow)

    async def scenario():
        task = asyncio.create_task(db._warmup(config=object()))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
