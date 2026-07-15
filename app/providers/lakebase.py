"""LakebaseProvider -- reads synced KPI aggregates from Lakebase (Postgres).

Serves KPI tiles, health cards and trend series from the two generic synced
aggregate tables (``agg_rollup_synced`` / ``agg_daily_synced``) over a Lakebase
connection authenticated as the app service principal (the Lakebase instance is
bound to the app as a resource). Interactive Genie / SQL Warehouse access stays
OBO; only these Postgres reads are SP-based.

Row-level drill-downs (account inventory, findings queue) and per-incident
records are not carried in the aggregate sync; those methods delegate to the
SeedProvider so the demo drill-downs remain populated. A production deployment
would either add dimensional synced tables or route drill-downs through the
interactive Genie / SQL Warehouse path.

KPI values are rendered from the config's measure definitions (format, RAG
thresholds), so the semantic contract stays defined once in cyber360.yaml.
"""

from __future__ import annotations

import logging
from typing import Any

from core.config import (
    Cyber360Config,
    TrendDirection,
    format_measure_value,
    rag_for_measure,
    rollup_status,
)
from core.db import lakebase_connection
from models.common import Kpi, KpiLineage, Paginated, TrendInfo, TrendPoint
from models.domain import DomainMetricsResponse
from models.identity import AccountRow, AccountsQuery
from models.incidents import IncidentsResponse
from models.scorecard import (
    ComplianceCounts,
    DomainHealth,
    DomainHealthHighlight,
    ScorecardOrg,
    ScorecardResponse,
)
from models.vulnerability import FindingRow, FindingsQuery
from providers.seed import SeedProvider

logger = logging.getLogger(__name__)

DEFAULT_PERIOD = 30


class LakebaseProvider:
    """Data provider backed by the read-only synced Lakebase aggregates."""

    source = "lakebase"

    def __init__(self, config: Cyber360Config, token: str = ""):
        # token is accepted for factory-signature parity but intentionally
        # unused: Lakebase reads authenticate as the app service principal,
        # not per-user OBO.
        self.config = config
        self._rollup_table = config.lakebase.synced_tables.rollup
        self._daily_table = config.lakebase.synced_tables.daily
        # Demo drill-downs (accounts/findings/incidents) not in aggregate sync.
        self._seed = SeedProvider(config)

    # ── low-level reads ──

    async def _fetch(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        async with lakebase_connection(self.config) as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, row)) for row in await cur.fetchall()]

    async def _rollup(self, period: int = DEFAULT_PERIOD) -> dict[tuple[str, str], dict]:
        rows = await self._fetch(
            f"SELECT domain, measure, value, prev_value, delta "
            f"FROM {self._rollup_table} WHERE period = %s",
            (period,),
        )
        return {(r["domain"], r["measure"]): r for r in rows}

    async def _daily(self, domain: str) -> list[dict]:
        return await self._fetch(
            f"SELECT day, measure, value FROM {self._daily_table} "
            f"WHERE domain = %s ORDER BY day",
            (domain,),
        )

    # ── KPI construction ──

    def _build_kpi(self, domain_key: str, measure_name: str, row: dict | None) -> Kpi:
        measure = self.config.get_measure(domain_key, measure_name)
        raw = float(row["value"]) if row and row.get("value") is not None else 0.0
        delta = float(row["delta"]) if row and row.get("delta") is not None else 0.0

        trend = None
        if measure and measure.trend:
            trend = TrendInfo(direction=measure.trend.direction, label=measure.trend.label)
        elif row is not None:
            direction = (
                TrendDirection.up if delta > 0
                else TrendDirection.down if delta < 0
                else TrendDirection.flat
            )
            trend = TrendInfo(direction=direction, label=f"{delta:+.1f} vs prev period")

        if measure is None:
            return Kpi(key=measure_name, label=measure_name, value=str(raw), raw=raw,
                       status="green", caption="", trend=trend, lineage=None)

        return Kpi(
            key=measure.name,
            label=measure.label,
            value=format_measure_value(measure, raw),
            raw=raw,
            status=rag_for_measure(measure, raw),
            caption=measure.caption,
            trend=trend,
            lineage=KpiLineage(
                measure=measure.name,
                expression=measure.expression,
                comment=measure.comment,
            ),
        )

    # ── public API ──

    async def get_scorecard(self) -> ScorecardResponse:
        rollup = await self._rollup(DEFAULT_PERIOD)

        top_line_kpis: list[Kpi] = []
        for t in self.config.top_line_kpis:
            row = rollup.get((t.domain, t.measure))
            kpi = self._build_kpi(t.domain, t.measure, row)
            if t.caption:
                kpi.caption = t.caption
            if t.trend:
                kpi.trend = TrendInfo(direction=t.trend.direction, label=t.trend.label)
            top_line_kpis.append(kpi)

        domains: list[DomainHealth] = []
        for domain in self.config.domains:
            kpis = [
                self._build_kpi(domain.key, m.name, rollup.get((domain.key, m.name)))
                for m in domain.metric_view.measures
            ]
            compliance = ComplianceCounts(green=0, amber=0, red=0, total=len(kpis))
            for k in kpis:
                if k.status == "green":
                    compliance.green += 1
                elif k.status == "amber":
                    compliance.amber += 1
                else:
                    compliance.red += 1

            score_vals = [
                float((rollup.get((domain.key, n)) or {}).get("value") or 0)
                for n in domain.health.score_measures
            ]
            score = round(sum(score_vals) / max(len(score_vals), 1))

            highlights: list[DomainHealthHighlight] = []
            for name in domain.health.highlights:
                kpi = next((k for k in kpis if k.key == name), None)
                if kpi:
                    highlights.append(DomainHealthHighlight(
                        label=kpi.label, value=kpi.value, status=kpi.status
                    ))

            domains.append(DomainHealth(
                key=domain.key,
                label=domain.short,
                status=rollup_status([k.status for k in kpis]),
                score=score,
                compliance=compliance,
                highlights=highlights,
            ))

        return ScorecardResponse(
            org=ScorecardOrg(name=self.config.org.name, caregivers=68000, cyber_staff=200),
            top_line_kpis=top_line_kpis,
            domains=domains,
        )

    async def get_domain_metrics(self, domain_key: str) -> DomainMetricsResponse:
        domain = self.config.get_domain(domain_key)
        if not domain:
            raise ValueError(f"Unknown domain: {domain_key}")

        rollup = await self._rollup(DEFAULT_PERIOD)
        kpis = [
            self._build_kpi(domain_key, m.name, rollup.get((domain_key, m.name)))
            for m in domain.metric_view.measures
        ]

        # Trend: one multi-measure series keyed by day, from the daily aggregate.
        daily = await self._daily(domain_key)
        by_day: dict[str, dict[str, float]] = {}
        for r in daily:
            day = str(r["day"])
            by_day.setdefault(day, {})[r["measure"]] = (
                round(float(r["value"]), 2) if r["value"] is not None else 0.0
            )
        series = [TrendPoint(day=day, values=vals) for day, vals in sorted(by_day.items())]

        return DomainMetricsResponse(
            key=domain_key,
            label=domain.label,
            status=rollup_status([k.status for k in kpis]),
            kpis=kpis,
            trends={"daily": series},
            breakdowns={},
        )

    # ── drill-downs not carried in aggregate sync -> demo data ──

    async def get_accounts(self, query: AccountsQuery) -> Paginated[AccountRow]:
        return await self._seed.get_accounts(query)

    async def get_findings(self, query: FindingsQuery) -> Paginated[FindingRow]:
        return await self._seed.get_findings(query)

    async def get_incidents(self) -> IncidentsResponse:
        return await self._seed.get_incidents()
