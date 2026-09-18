"""Unit tests for the generic, config-driven SeedProvider.

Prove the seed (local) provider computes KPIs, trend, and drill-down rows for
ANY configured domain from the config measure expressions + generator rows --
no per-domain code -- so `make dev` matches the deployed metricview shape.

Skipped if duckdb (the seed engine) is unavailable.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.config import load_config
from models.detail import DetailQuery
from providers.seed import SeedProvider

pytest.importorskip("duckdb")


@pytest.fixture
def config():
    return load_config(Path(__file__).parent.parent / "cyber-unified.yaml")


def test_scorecard_computes_measures_from_config(config):
    sc = asyncio.run(SeedProvider(config).get_scorecard(30))
    assert sc.top_line_kpis, "expected top-line KPIs"
    # Every configured domain gets a health card, computed generically.
    assert {d.key for d in sc.domains} == {d.key for d in config.domains}
    # Click rate is a percent measure -> "NN.NN%".
    click = next(k for k in sc.top_line_kpis if k.key == "phishing_click_rate")
    assert click.value.endswith("%") and float(click.value[:-1]) > 0


def test_domain_metrics_has_trend(config):
    dm = asyncio.run(SeedProvider(config).get_domain_metrics("phishing", 30))
    assert len(dm.kpis) == len(config.get_domain("phishing").metric_view.measures)
    assert dm.trends["daily"], "expected a daily trend series over the window"


def test_detail_rows_are_config_driven(config):
    p = SeedProvider(config)
    resp = asyncio.run(p.get_detail_rows("phishing", DetailQuery(filter_key="clicked", page=1, page_size=5)))
    # Columns mirror the detail_table config; the filter narrows to clicks.
    assert [c.field for c in resp.columns] == [
        c.field for c in config.get_domain("phishing").detail_table.columns]
    assert 0 < resp.total < 1800  # a subset (clicks only), not the whole table
    assert all(r["eventtype"] == "Email Click" for r in resp.rows)


def test_measure_math_matches_metric_view_expr(config):
    """The seed engine evaluates the SAME portable expression the metric view
    uses, so a config edit propagates to local dev with no code change."""
    domain = config.get_domain("phishing")
    click = next(m for m in domain.metric_view.measures if m.name == "phishing_click_rate")
    # Portable SQL (identical to mv_phishing.sql) -- no engine-specific funcs.
    assert "try_divide" not in click.expression
    assert "NULLIF(COUNT(*), 0)" in click.expression
