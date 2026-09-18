"""Unit tests for MetricViewProvider.

Mock the SQLClient so no warehouse is needed. Verify:
  * the MEASURE()/GROUP BY SQL is built against the right metric view + windows,
  * current/prior windows produce the expected period-over-period delta,
  * the sparse-prior guard falls back to synthesized change (as the old provider),
  * scorecard/domain shapes + RAG statuses come out correct.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.config import DimensionConfig, load_config
from providers.metricview import MetricViewProvider


class FakeSQLClient:
    """Records queries and returns canned rows keyed by a substring match."""

    def __init__(self, responses: list[tuple[str, list[dict]]]):
        self._responses = responses
        self.queries: list[str] = []

    def execute(self, sql: str, *, token: str = "") -> list[dict]:
        self.queries.append(sql)
        for needle, rows in self._responses:
            if needle in sql:
                return rows
        return []


@pytest.fixture
def config():
    return load_config(Path(__file__).parent.parent / "cyber-unified.yaml")


def _with_time_dim(config, dim: str = "day"):
    """Copy of the config whose phishing view DECLARES a time dimension.

    The shipped config has time_dimension: "" because the live edp_dev view has no
    date dimension. Windowing/trend behaviour still needs coverage, so tests that
    exercise it opt in explicitly rather than assuming the shipped shape.
    """
    domain = config.domains[0]
    mv = domain.metric_view.model_copy(update={
        "time_dimension": dim,
        "dimensions": [
            DimensionConfig(name=dim, expression="CAST(eventtimestamp AS DATE)"),
            *domain.metric_view.dimensions,
        ],
    })
    return config.model_copy(update={
        "domains": [domain.model_copy(update={"metric_view": mv})]
    })


def _provider(config, sql_client) -> MetricViewProvider:
    config = config.model_copy(
        update={
            "data_source": config.data_source.model_copy(
                # schema_ is the field (aliased "schema"); set by field name here.
                update={"provider": "metricview", "warehouse_id": "wh", "catalog": "cat", "schema_": "sch"}
            )
        }
    )
    p = MetricViewProvider(config, token="user-tok")
    p._sql = sql_client
    return p


def test_measure_query_targets_metric_view_and_window(config):
    cfg = _with_time_dim(config)
    fake = FakeSQLClient([("phishing_detail_metric_view", [{"Click Rate": 0.11}])])
    p = _provider(cfg, fake)

    asyncio.run(p._measure_row(
        "phishing_detail_metric_view", ["Click Rate"],
        p._window_where(cfg.domains[0], 30, prior=False)))

    q = fake.queries[-1]
    assert "MEASURE(`Click Rate`)" in q
    assert "cat.sch.phishing_detail_metric_view" in q
    assert "current_date() - INTERVAL 30 DAY" in q


def test_prior_window_where_is_previous_period(config):
    # A 30-day prior window is [60d ago, 30d ago).
    cfg = _with_time_dim(config)
    p = _provider(cfg, FakeSQLClient([]))
    where = p._window_where(cfg.domains[0], 30, prior=True)
    assert "INTERVAL 60 DAY" in where and "INTERVAL 30 DAY" in where and "<" in where
    assert "`day`" in where


def test_window_uses_the_configured_dimension_name(config):
    # The date dimension is NEVER assumed to be called "day".
    cfg = _with_time_dim(config, "event_date")
    p = _provider(cfg, FakeSQLClient([]))
    where = p._window_where(cfg.domains[0], 30, prior=False)
    assert "`event_date`" in where
    assert "`day`" not in where


def test_no_time_dimension_means_no_date_predicate(config):
    # The shipped config has time_dimension: "" (the live edp_dev view has no date
    # dimension). Referencing one produced UNRESOLVED_COLUMN in production.
    p = _provider(config, FakeSQLClient([]))
    domain = config.domains[0]
    assert p._window_where(domain, 30, prior=False) == ""
    assert p._window_where(domain, 30, prior=True) == ""


def test_no_time_dimension_issues_one_unwindowed_query(config):
    row = {m.name: 0.5 for m in config.domains[0].metric_view.measures}
    fake = FakeSQLClient([("phishing_detail_metric_view", [row])])
    p = _provider(config, fake)

    asyncio.run(p._rollup_for_domain(config.domains[0], 30))

    # ONE query, and it carries no WHERE at all.
    assert len(fake.queries) == 1, fake.queries
    assert "WHERE" not in fake.queries[0]
    assert "current_date()" not in fake.queries[0]


def test_no_time_dimension_yields_no_trend_series(config):
    fake = FakeSQLClient([])
    p = _provider(config, fake)
    series = asyncio.run(p._trend_series(config.domains[0], 30))
    assert series == []
    # and it must not have issued a GROUP BY on a non-existent column
    assert not any("GROUP BY" in q for q in fake.queries)


def test_trend_groups_by_configured_dimension(config):
    cfg = _with_time_dim(config, "event_date")
    names = [m.name for m in cfg.domains[0].metric_view.measures]
    row = {"event_date": "2026-09-01", **{n: 0.5 for n in names}}
    fake = FakeSQLClient([("GROUP BY", [row])])
    p = _provider(cfg, fake)

    series = asyncio.run(p._trend_series(cfg.domains[0], 30))

    q = next(q for q in fake.queries if "GROUP BY" in q)
    assert "GROUP BY `event_date`" in q and "ORDER BY `event_date`" in q
    assert len(series) == 1 and series[0].day == "2026-09-01"


def test_scale_converts_fraction_to_percent(config):
    # The live view returns rates as 0-1 fractions; config `scale: 100` renders
    # them as percentages, and RAG compares in DISPLAY units.
    p = _provider(config, FakeSQLClient([]))
    kpi = p._build_kpi("phishing", "Click Rate", cur=0.1161, prev=None, period=30)
    assert kpi.raw == pytest.approx(11.61, abs=0.01)
    assert "11.61%" == kpi.value
    # goal lower, green 5 / amber 10 -> 11.61 is red
    assert kpi.status == "red"


def test_count_measure_is_not_scaled(config):
    p = _provider(config, FakeSQLClient([]))
    kpi = p._build_kpi("phishing", "count", cur=1800.0, prev=None, period=30)
    assert kpi.raw == 1800.0
    assert kpi.value == "1,800"


def test_real_delta_when_prior_well_populated(config):
    # Report Rate goal is "higher": current 0.20 -> 20%, prior 0.15 -> 15%, so
    # +5 pts and prior >= 0.5*current.
    p = _provider(config, FakeSQLClient([]))
    kpi = p._build_kpi("phishing", "Report Rate", cur=0.20, prev=0.15, period=30)
    assert kpi.raw == pytest.approx(20.0)
    assert kpi.change is not None
    # +5 percentage points, goal higher -> positive tone
    assert kpi.change.tone == "positive"


def test_sparse_prior_falls_back_to_synthesis(config):
    # prior is 0 (empty window) -> guard fails -> synthesized change (never None,
    # and deterministic), NOT a nonsensical full-value delta.
    p = _provider(config, FakeSQLClient([]))
    kpi = p._build_kpi("phishing", "Report Rate", cur=0.20, prev=0.0, period=30)
    assert kpi.change is not None
    # synthesized change is small relative to the value (not ~+20)
    assert "20" not in kpi.change.label


def test_detail_rows_query_is_config_driven(config):
    # The generic drill-down SELECTs the configured columns from the published
    # metric view, applies the chosen filter's WHERE, and paginates -- all config.
    from models.detail import DetailQuery

    # Derive the expected columns FROM CONFIG -- hardcoding them here is how a
    # stale field name (campaignname, dropped by the view's EXCEPT wildcard)
    # survived into production.
    expected = [c.field for c in config.domains[0].detail_table.columns]
    fake = FakeSQLClient([
        ("COUNT(*)", [{"n": 209}]),
        ("SELECT `", [{f: "x" for f in expected}]),
    ])
    p = _provider(config, fake)
    resp = asyncio.run(p.get_detail_rows("phishing", DetailQuery(filter_key="clicked", page=1, page_size=5)))

    assert resp.total == 209
    assert [c.field for c in resp.columns] == expected
    # the configured filter's trusted WHERE fragment was applied
    rows_q = next(q for q in fake.queries if q.startswith("SELECT `") and "COUNT(*)" not in q)
    assert "eventtype = 'Email Click'" in rows_q
    assert "LIMIT 5 OFFSET 0" in rows_q
    # The drill-down reads the SAME already-published metric view the KPIs use --
    # NOT an invented pass-through view, and NOT the underlying source table (which
    # the app has no privilege on, and no longer knows about).
    assert "cat.sch.phishing_detail_metric_view" in rows_q
    assert "phishing_source" not in rows_q


def test_scorecard_builds_from_measure_rows(config):
    # Return the same measure row for any current/prior window query.
    row = {m.name: 50.0 for d in config.domains for m in d.metric_view.measures}
    fake = FakeSQLClient([("FROM cat.sch.phishing_detail_metric_view", [row])])
    p = _provider(config, fake)

    sc = asyncio.run(p.get_scorecard(30))
    assert sc.top_line_kpis, "expected top-line KPIs"
    assert sc.domains, "expected domain health cards"
    # The shipped view has no time dimension -> ONE unwindowed query per domain.
    assert len(fake.queries) == len(config.domains)
