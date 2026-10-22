"""The app connects to whatever Lakebase branch the SCM extension paired.

On every git checkout the Lakebase SCM extension rewrites .env's branch block
(LAKEBASE_HOST / DB_USERNAME, plus our DB_NAME). `make local` loads it, so those
keys must reach the DSN -- with the explicit PG* overrides still winning.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import db
from core.config import load_config

CONFIG = Path(__file__).parent.parent / "cyber-unified.yaml"
PG_KEYS = ("PGHOST", "PGUSER", "PGDATABASE", "LAKEBASE_HOST", "DB_USERNAME",
           "DB_NAME", "DATABRICKS_CLIENT_ID")


@pytest.fixture
def config(monkeypatch):
    for key in PG_KEYS:
        monkeypatch.delenv(key, raising=False)
    return load_config(CONFIG)


def test_dsn_uses_the_scm_extension_keys(config, monkeypatch):
    monkeypatch.setenv("LAKEBASE_HOST", "ep-pr-7.database.example.com")
    monkeypatch.setenv("DB_USERNAME", "dev@example.com")
    monkeypatch.setenv("DB_NAME", "cyber-unified-dev")
    dsn = db._lakebase_dsn(config, "tok")
    assert "host=ep-pr-7.database.example.com" in dsn
    assert "user=dev@example.com" in dsn
    assert "dbname=cyber-unified-dev" in dsn


def test_explicit_pg_overrides_win(config, monkeypatch):
    monkeypatch.setenv("LAKEBASE_HOST", "ep-ext.example.com")
    monkeypatch.setenv("DB_USERNAME", "ext-user")
    monkeypatch.setenv("DB_NAME", "ext-db")
    monkeypatch.setenv("PGHOST", "pg.example.com")
    monkeypatch.setenv("PGUSER", "pg-user")
    monkeypatch.setenv("PGDATABASE", "pg-db")
    dsn = db._lakebase_dsn(config, "tok")
    assert "host=pg.example.com" in dsn
    assert "user=pg-user" in dsn
    assert "dbname=pg-db" in dsn
