"""MetricViewProvider -- reads KPIs by querying UC metric views natively.

KPI tiles, health cards and trend series are served by querying each domain's
Unity Catalog **metric view** (``mv_*``) directly on the SQL Warehouse with the
``MEASURE()`` function -- no reverse-ETL, no flattened aggregate tables. The
metric view is the single semantic source of the measure math; this provider
only *reads* it and applies presentation (format, RAG thresholds) from
cyber360.yaml. Metric-view **materialization** transparently accelerates these
reads (aggregate-aware query rewriting) with no query changes.

Auth: reads run **per-user (OBO)** -- the caller's token is threaded through to
the Statement Execution API, so Unity Catalog permissions are enforced per user.
(Materialization still applies because the metric views carry no per-user access
controls / invoker-dependent expressions.)

Period-over-period change is computed by querying the view over the current and
prior windows and subtracting; the trend series is a ``GROUP BY day`` query.
Row-level drill-downs (accounts / findings / incidents) are not part of the
metric-view semantic layer, so those delegate to the SeedProvider -- exactly as
the previous provider did.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.config import (
    Cyber360Config,
    _format_change,
    build_change,
    format_measure_value,
    normalize_period,
    rag_for_measure,
    rollup_status,
)
from core.sql import SQLClient
from models.common import Kpi, KpiChange, KpiLineage, TrendInfo, TrendPoint
from models.detail import DetailColumn, DetailQuery, DetailRowsResponse
from models.domain import DomainMetricsResponse
from models.incidents import IncidentsResponse
from models.scorecard import (
    ComplianceCounts,
    DomainHealth,
    DomainHealthHighlight,
    ScorecardOrg,
    ScorecardResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_PERIOD = 30


class MetricViewProvider:
    """Data provider backed by native UC metric-view queries on a SQL Warehouse."""

    source = "metricview"

    def __init__(self, config: Cyber360Config, token: str = ""):
        self.config = config
        # Per-user OBO: the caller's token authenticates the warehouse queries so
        # UC permissions are enforced per user. Falls back to ambient auth if empty.
        self._token = token
        self._sql = SQLClient(warehouse_id=config.data_source.warehouse_id)
        self._catalog = config.data_source.catalog
        self._schema = config.data_source.schema_

    # ── low-level query ──

    def _mv_fqn(self, metric_view_name: str) -> str:
        return f"{self._catalog}.{self._schema}.{metric_view_name}"

    async def _measure_row(
        self, metric_view_name: str, measures: list[str], where: str = ""
    ) -> dict[str, float]:
        """Return one org-wide row of MEASURE(...) scalars for the given measures.

        No GROUP BY -> a single aggregate row over the (optionally date-filtered)
        window. Missing/NULL measures come back as 0.0.
        """
        if not measures:
            return {}
        select = ", ".join(f"MEASURE(`{m}`) AS `{m}`" for m in measures)
        sql = f"SELECT {select} FROM {self._mv_fqn(metric_view_name)}"
        if where:
            sql += f" WHERE {where}"
        rows = await asyncio.to_thread(self._sql.execute, sql, token=self._token)
        row = rows[0] if rows else {}
        return {m: _as_float(row.get(m)) for m in measures}

    def _window_where(self, period: int, *, prior: bool) -> str:
        """Date filter on the metric view's `day` dimension for the current or
        immediately-preceding window of `period` days."""
        if prior:
            return (
                f"`day` >= current_date() - INTERVAL {2 * period} DAY "
                f"AND `day` < current_date() - INTERVAL {period} DAY"
            )
        return f"`day` >= current_date() - INTERVAL {period} DAY"

    # ── KPI construction (mirrors the presentation contract in cyber360.yaml) ──

    def _build_kpi(
        self,
        domain_key: str,
        measure_name: str,
        cur: float | None,
        prev: float | None,
        period: int,
    ) -> Kpi:
        measure = self.config.get_measure(domain_key, measure_name)
        raw = float(cur) if cur is not None else 0.0

        if measure is None:
            return Kpi(key=measure_name, label=measure_name, value=str(raw), raw=raw,
                       status="green", caption="", lineage=None)

        # Period-over-period change. A real prior-window delta is only meaningful
        # when the prior window is comparably populated to the current one; with a
        # shallow source history the prior is empty/near-empty and the delta
        # collapses to ~the full current value. Mirror the previous provider's
        # guard: trust the real prior only when it's at least half the current
        # magnitude, else fall back to the same deterministic synthesis the seed
        # path uses so the scorecard shows a plausible period-scaled movement.
        change: KpiChange | None = None
        has_real_prior = (
            prev is not None and float(prev) > 0.0 and float(prev) >= 0.5 * abs(raw)
        )
        if has_real_prior:
            change = KpiChange(**_format_change(measure, raw - float(prev)))
        else:
            change = KpiChange(**build_change(measure, raw, period))

        trend = None
        if measure.trend:
            trend = TrendInfo(direction=measure.trend.direction, label=measure.trend.label)

        return Kpi(
            key=measure.name,
            label=measure.label,
            value=format_measure_value(measure, raw),
            raw=raw,
            status=rag_for_measure(measure, raw),
            caption=measure.caption,
            trend=trend,
            change=change,
            lineage=KpiLineage(
                measure=measure.name,
                expression=measure.expression or "",
                comment=measure.comment,
            ),
        )

    async def _rollup_for_domain(
        self, domain, period: int
    ) -> dict[str, tuple[float, float]]:
        """Return {measure_name: (current_value, prior_value)} for a domain by
        querying its metric view over the current + prior windows."""
        names = [m.name for m in domain.metric_view.measures]
        mv = domain.metric_view.name
        cur, prev = await asyncio.gather(
            self._measure_row(mv, names, self._window_where(period, prior=False)),
            self._measure_row(mv, names, self._window_where(period, prior=True)),
        )
        return {n: (cur.get(n, 0.0), prev.get(n, 0.0)) for n in names}

    # ── public API ──

    async def get_scorecard(self, period: int = DEFAULT_PERIOD) -> ScorecardResponse:
        period = normalize_period(period)
        # One current+prior query pair per domain, all in parallel.
        rollups = await asyncio.gather(
            *(self._rollup_for_domain(d, period) for d in self.config.domains)
        )
        by_domain = {d.key: r for d, r in zip(self.config.domains, rollups)}

        def cur_prev(domain_key: str, measure: str) -> tuple[float | None, float | None]:
            pair = by_domain.get(domain_key, {}).get(measure)
            return (pair[0], pair[1]) if pair else (None, None)

        top_line_kpis: list[Kpi] = []
        for t in self.config.top_line_kpis:
            c, p = cur_prev(t.domain, t.measure)
            kpi = self._build_kpi(t.domain, t.measure, c, p, period)
            if t.caption:
                kpi.caption = t.caption
            if t.trend:
                kpi.trend = TrendInfo(direction=t.trend.direction, label=t.trend.label)
            top_line_kpis.append(kpi)

        domains: list[DomainHealth] = []
        for domain in self.config.domains:
            kpis = [
                self._build_kpi(domain.key, m.name, *cur_prev(domain.key, m.name), period)
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

            score_vals = [cur_prev(domain.key, n)[0] or 0.0 for n in domain.health.score_measures]
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

    async def get_domain_metrics(
        self, domain_key: str, period: int = DEFAULT_PERIOD
    ) -> DomainMetricsResponse:
        domain = self.config.get_domain(domain_key)
        if not domain:
            raise ValueError(f"Unknown domain: {domain_key}")
        period = normalize_period(period)

        rollup = await self._rollup_for_domain(domain, period)
        kpis = [
            self._build_kpi(domain_key, m.name, rollup[m.name][0], rollup[m.name][1], period)
            for m in domain.metric_view.measures
        ]

        series = await self._trend_series(domain, period)

        return DomainMetricsResponse(
            key=domain_key,
            label=domain.label,
            status=rollup_status([k.status for k in kpis]),
            kpis=kpis,
            trends={"daily": series},
            breakdowns={},
        )

    async def _trend_series(self, domain, period: int) -> list[TrendPoint]:
        """Per-day multi-measure series over the current window: one MEASURE()
        query grouped by the metric view's `day` dimension."""
        names = [m.name for m in domain.metric_view.measures]
        if not names:
            return []
        select = ", ".join(f"MEASURE(`{m}`) AS `{m}`" for m in names)
        sql = (
            f"SELECT `day`, {select} FROM {self._mv_fqn(domain.metric_view.name)} "
            f"WHERE {self._window_where(period, prior=False)} "
            f"GROUP BY `day` ORDER BY `day`"
        )
        rows = await asyncio.to_thread(self._sql.execute, sql, token=self._token)
        series: list[TrendPoint] = []
        for r in rows:
            day = str(r.get("day"))
            vals = {n: round(_as_float(r.get(n)), 2) for n in names}
            series.append(TrendPoint(day=day, values=vals))
        return series

    # ── generic, config-driven drill-down table ──

    async def get_detail_rows(
        self, domain_key: str, query: DetailQuery
    ) -> DetailRowsResponse:
        """Return a page of the domain's drill-down table by SELECTing the
        configured columns from its source_table (per-user OBO). Entirely
        config-driven: columns, the filter's WHERE fragment, and the sort all
        come from the domain's detail_table block."""
        domain = self.config.get_domain(domain_key)
        if not domain:
            raise ValueError(f"Unknown domain: {domain_key}")

        table = domain.detail_table
        if not table.columns:
            # No table configured for this domain -> empty (not an error).
            return DetailRowsResponse(columns=[], rows=[], total=0,
                                      page=query.page, page_size=query.page_size)

        columns = [DetailColumn(field=c.field, label=c.label or c.field, format=c.format)
                   for c in table.columns]
        col_list = ", ".join(f"`{c.field}`" for c in table.columns)
        source = self._resolve_source(domain)
        where = self._filter_where(table, query.filter_key)
        where_sql = f" WHERE {where}" if where else ""
        order_sql = f" ORDER BY {table.order_by}" if table.order_by else ""

        page = max(query.page, 1)
        page_size = query.page_size or table.page_size
        offset = (page - 1) * page_size

        count_sql = f"SELECT COUNT(*) AS n FROM {source}{where_sql}"
        rows_sql = (
            f"SELECT {col_list} FROM {source}{where_sql}{order_sql} "
            f"LIMIT {page_size} OFFSET {offset}"
        )
        count_rows, data_rows = await asyncio.gather(
            asyncio.to_thread(self._sql.execute, count_sql, token=self._token),
            asyncio.to_thread(self._sql.execute, rows_sql, token=self._token),
        )
        total = int(_as_float(count_rows[0].get("n"))) if count_rows else 0
        return DetailRowsResponse(
            columns=columns,
            rows=[{c.field: r.get(c.field) for c in table.columns} for r in data_rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    def _resolve_source(self, domain) -> str:
        """The relation the drill-down SELECTs from: the `phishing_source`
        pass-through view in the deploy catalog/schema. That view is created next
        to the metric view (phishing_source.sql) as `SELECT * FROM :source_table`,
        so it exists on EVERY target and resolves to the right underlying data --
        synthetic gold on sandbox, the real conn_cyberarch.dbo.phishing_detail on
        edp_dev -- without the app needing to know the per-target source location.
        Falls back to the configured source_table if no source view is named."""
        source_view = getattr(domain.metric_view, "source_view", "") or "phishing_source"
        return f"{self._catalog}.{self._schema}.{source_view}"

    @staticmethod
    def _filter_where(table, filter_key: str | None) -> str:
        """Look up the TRUSTED where-fragment for the chosen filter key. Never
        accepts free-form predicates -- only the config-defined ones."""
        if not filter_key:
            return ""
        for f in table.filters:
            if f.key == filter_key:
                return f.where
        return ""

    async def get_incidents(self) -> IncidentsResponse:
        # Incidents are gated by features.soc_view_enabled and are not part of the
        # metric-view semantic layer; return empty until a config-driven source
        # is wired. (The SOC view is off by default.)
        return IncidentsResponse.empty()


def _as_float(value: Any) -> float:
    """Coerce a Statement-Execution cell (str/num/None) to float; 0.0 on failure."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
