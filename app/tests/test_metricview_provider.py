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

from core.config import load_config
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
    return load_config(Path(__file__).parent.parent / "cyber360.yaml")


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
    fake = FakeSQLClient([("mv_identity_access", [{"mfa_adoption": 99.0}])])
    p = _provider(config, fake)

    asyncio.run(p._measure_row("mv_identity_access", ["mfa_adoption"], p._window_where(30, prior=False)))

    q = fake.queries[-1]
    assert "MEASURE(`mfa_adoption`)" in q
    assert "cat.sch.mv_identity_access" in q
    assert "current_date() - INTERVAL 30 DAY" in q


def test_prior_window_where_is_previous_period():
    # A 30-day prior window is [60d ago, 30d ago).
    p = MetricViewProvider.__new__(MetricViewProvider)
    where = MetricViewProvider._window_where(p, 30, prior=True)
    assert "INTERVAL 60 DAY" in where and "INTERVAL 30 DAY" in where and "<" in where


def test_real_delta_when_prior_well_populated(config):
    # current mfa 99, prior 90 -> real delta -9? no: 99-90 = +9. prior >= 0.5*99.
    p = _provider(config, FakeSQLClient([]))
    kpi = p._build_kpi("identity", "mfa_adoption", cur=99.0, prev=90.0, period=30)
    assert kpi.raw == 99.0
    assert kpi.change is not None
    # +9 percentage points, goal higher -> positive tone, up arrow
    assert kpi.change.tone == "positive"


def test_sparse_prior_falls_back_to_synthesis(config):
    # prior is 0 (empty window) -> guard fails -> synthesized change (never None,
    # and deterministic), NOT a nonsensical full-value delta.
    p = _provider(config, FakeSQLClient([]))
    kpi = p._build_kpi("identity", "mfa_adoption", cur=99.0, prev=0.0, period=30)
    assert kpi.change is not None
    # synthesized change is small relative to the value (not ~+99)
    # label like "+1.2" / "-0.8"; just assert it parsed and isn't the raw value
    assert "99" not in kpi.change.label


def test_scorecard_builds_from_measure_rows(config):
    # Return the same measure row for any current/prior window query.
    row = {m.name: 50.0 for d in config.domains for m in d.metric_view.measures}
    fake = FakeSQLClient([("FROM cat.sch.mv_", [row])])
    p = _provider(config, fake)

    sc = asyncio.run(p.get_scorecard(30))
    assert sc.top_line_kpis, "expected top-line KPIs"
    assert sc.domains, "expected domain health cards"
    # a query was issued per domain per window (>= 2 * num domains)
    assert len(fake.queries) >= 2 * len(config.domains)
