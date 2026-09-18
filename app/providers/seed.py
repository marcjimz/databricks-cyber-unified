"""SeedProvider -- generic, config-driven local provider (zero workspace deps).

Used for `make dev` and any deployment with `provider: seed`. It computes EVERY
domain's KPIs, trend, and drill-down rows generically:

  * the synthetic rows come from ``pipelines/lib/generator.py`` -- the SAME
    generator the Lakeflow pipeline uses to land the gold table, so the seed
    story matches the deployed one;
  * the measure math is evaluated by running each domain's config measure
    ``expression`` (the IDENTICAL portable SQL that lives in the metric view)
    against those rows in an in-process **DuckDB** engine.

There is NO per-domain code here (no ``if domain == 'identity'``). Adding a
domain to ``cyber-unified.yaml`` + a generator makes the seed provider serve it with
zero changes -- mirroring the metric-view provider's config-driven contract.

DuckDB is an OPTIONAL dependency: if it (or the generator) is unavailable, the
provider degrades to zeros rather than failing, so the production ``metricview``
path never depends on it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from core.config import (
    CyberUnifiedConfig,
    DomainConfig,
    _format_change,
    build_change,
    format_measure_value,
    normalize_period,
    rag_for_measure,
    rollup_status,
)
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


def _load_generator():
    """Import the shared synthetic generator lazily (keeps it optional)."""
    import sys
    from pathlib import Path

    # pipelines/ lives next to app/ in the repo; add it to the path once.
    repo_root = Path(__file__).resolve().parents[2]
    pipelines = repo_root / "pipelines"
    if pipelines.is_dir() and str(pipelines) not in sys.path:
        sys.path.insert(0, str(pipelines))
    from lib.generator import GOLD_GENERATORS, generate_gold  # type: ignore

    return GOLD_GENERATORS, generate_gold


class SeedProvider:
    """In-memory, config-driven provider backed by DuckDB over synthetic rows."""

    source = "seed"

    def __init__(self, config: CyberUnifiedConfig):
        self.config = config
        self._con = None  # lazy DuckDB connection
        self._registered: set[str] = set()

    # ── DuckDB engine ──

    def _connect(self):
        if self._con is not None:
            return self._con
        try:
            import duckdb
        except ImportError:
            logger.warning("duckdb not installed -- seed provider returns zeros. "
                           "`pip install cyber-unified[dev]` for local KPIs.")
            self._con = False  # sentinel: tried and unavailable
            return self._con
        self._con = duckdb.connect()
        return self._con

    def _gold_table_name(self, domain: DomainConfig) -> str:
        """Unqualified gold-table name from the domain's source_table (last part)."""
        return domain.metric_view.source_table.split(".")[-1]

    def _ensure_registered(self, domain: DomainConfig) -> str | None:
        """Materialize the domain's synthetic gold rows into a DuckDB table named
        after its gold table. Returns the table name, or None if unavailable."""
        con = self._connect()
        if not con:
            return None
        table = self._gold_table_name(domain)
        if table in self._registered:
            return table
        try:
            _, generate_gold = _load_generator()
            rows = generate_gold(table)
        except Exception as exc:  # noqa: BLE001 -- generator optional/missing
            logger.warning("No synthetic generator for '%s': %s", table, exc)
            return None
        if not rows:
            return None
        self._create_table(con, table, rows)
        self._registered.add(table)
        return table

    @staticmethod
    def _create_table(con, table: str, rows: list[dict]) -> None:
        """Create + populate a typed DuckDB table from a list of dicts, inferring
        each column's type from its first non-null value (no pyarrow needed)."""
        cols = list(rows[0].keys())

        def duck_type(field: str) -> str:
            for r in rows:
                v = r.get(field)
                if v is None:
                    continue
                if isinstance(v, bool):
                    return "BOOLEAN"
                if isinstance(v, int):
                    return "BIGINT"
                if isinstance(v, float):
                    return "DOUBLE"
                if isinstance(v, (datetime, date)):
                    return "TIMESTAMP"
                return "VARCHAR"
            return "VARCHAR"

        coldefs = ", ".join(f'"{c}" {duck_type(c)}' for c in cols)
        con.execute(f'CREATE TABLE "{table}" ({coldefs})')
        placeholders = ", ".join("?" for _ in cols)
        con.executemany(
            f'INSERT INTO "{table}" VALUES ({placeholders})',
            [[r.get(c) for c in cols] for r in rows],
        )

    def _query(self, sql: str) -> list[dict]:
        con = self._connect()
        if not con:
            return []
        try:
            cur = con.execute(sql)
            names = [d[0] for d in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]
        except Exception as exc:  # noqa: BLE001
            logger.warning("seed query failed: %s\n%s", exc, sql)
            return []

    # ── measure evaluation (same portable exprs as the metric view) ──

    def _day_expr(self, domain: DomainConfig) -> str | None:
        for d in domain.metric_view.dimensions:
            if d.name == "day":
                return d.expression
        return None

    def _window_where(self, domain: DomainConfig, period: int, *, prior: bool) -> str:
        day = self._day_expr(domain)
        if not day:
            return ""
        if prior:
            return (f"{day} >= current_date - INTERVAL {2 * period} DAY "
                    f"AND {day} < current_date - INTERVAL {period} DAY")
        return f"{day} >= current_date - INTERVAL {period} DAY"

    def _measure_row(
        self, domain: DomainConfig, table: str, where: str
    ) -> dict[str, float]:
        """One aggregate row of every measure over the (optionally windowed) data."""
        measures = domain.metric_view.measures
        selects = [f"({m.expression}) AS \"{m.name}\"" for m in measures if m.expression]
        if not selects:
            return {}
        sql = f'SELECT {", ".join(selects)} FROM "{table}"'
        if where:
            sql += f" WHERE {where}"
        rows = self._query(sql)
        row = rows[0] if rows else {}
        return {m.name: _as_float(row.get(m.name)) for m in measures}

    def _rollup_for_domain(
        self, domain: DomainConfig, period: int
    ) -> dict[str, tuple[float, float]]:
        table = self._ensure_registered(domain)
        names = [m.name for m in domain.metric_view.measures]
        if not table:
            return {n: (0.0, 0.0) for n in names}
        cur = self._measure_row(domain, table, self._window_where(domain, period, prior=False))
        prev = self._measure_row(domain, table, self._window_where(domain, period, prior=True))
        return {n: (cur.get(n, 0.0), prev.get(n, 0.0)) for n in names}

    # ── KPI construction (mirrors MetricViewProvider so seed==prod shape) ──

    def _build_kpi(
        self, domain_key: str, measure_name: str,
        cur: float | None, prev: float | None, period: int,
    ) -> Kpi:
        measure = self.config.get_measure(domain_key, measure_name)
        raw = float(cur) if cur is not None else 0.0
        if measure is None:
            return Kpi(key=measure_name, label=measure_name, value=str(raw), raw=raw,
                       status="green", caption="", lineage=None)

        has_real_prior = (prev is not None and float(prev) > 0.0
                          and float(prev) >= 0.5 * abs(raw))
        if has_real_prior:
            change = KpiChange(**_format_change(measure, raw - float(prev)))
        else:
            change = KpiChange(**build_change(measure, raw, period))

        trend = TrendInfo(direction=measure.trend.direction, label=measure.trend.label) \
            if measure.trend else None
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

    # ── public API (identical surface to MetricViewProvider) ──

    async def get_scorecard(self, period: int = DEFAULT_PERIOD) -> ScorecardResponse:
        period = normalize_period(period)
        by_domain = {d.key: self._rollup_for_domain(d, period) for d in self.config.domains}

        def cur_prev(dk: str, m: str) -> tuple[float | None, float | None]:
            pair = by_domain.get(dk, {}).get(m)
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
            kpis = [self._build_kpi(domain.key, m.name, *cur_prev(domain.key, m.name), period)
                    for m in domain.metric_view.measures]
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
                        label=kpi.label, value=kpi.value, status=kpi.status))

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

        rollup = self._rollup_for_domain(domain, period)
        kpis = [self._build_kpi(domain_key, m.name, rollup[m.name][0], rollup[m.name][1], period)
                for m in domain.metric_view.measures]
        series = self._trend_series(domain, period)

        return DomainMetricsResponse(
            key=domain_key,
            label=domain.label,
            status=rollup_status([k.status for k in kpis]),
            kpis=kpis,
            trends={"daily": series},
            breakdowns={},
        )

    def _trend_series(self, domain: DomainConfig, period: int) -> list[TrendPoint]:
        table = self._ensure_registered(domain)
        day = self._day_expr(domain)
        measures = domain.metric_view.measures
        if not table or not day or not measures:
            return []
        selects = [f"({m.expression}) AS \"{m.name}\"" for m in measures if m.expression]
        sql = (
            f'SELECT {day} AS day, {", ".join(selects)} FROM "{table}" '
            f"WHERE {self._window_where(domain, period, prior=False)} "
            f"GROUP BY {day} ORDER BY day"
        )
        series: list[TrendPoint] = []
        for r in self._query(sql):
            series.append(TrendPoint(
                day=str(r.get("day")),
                values={m.name: round(_as_float(r.get(m.name)), 2) for m in measures},
            ))
        return series

    async def get_detail_rows(
        self, domain_key: str, query: DetailQuery
    ) -> DetailRowsResponse:
        domain = self.config.get_domain(domain_key)
        if not domain:
            raise ValueError(f"Unknown domain: {domain_key}")
        table_cfg = domain.detail_table
        table = self._ensure_registered(domain)
        if not table_cfg.columns or not table:
            return DetailRowsResponse(columns=[], rows=[], total=0,
                                      page=query.page, page_size=query.page_size)

        columns = [DetailColumn(field=c.field, label=c.label or c.field, format=c.format)
                   for c in table_cfg.columns]
        col_list = ", ".join(f'"{c.field}"' for c in table_cfg.columns)
        where = ""
        if query.filter_key:
            where = next((f.where for f in table_cfg.filters if f.key == query.filter_key), "")
        where_sql = f" WHERE {where}" if where else ""
        order_sql = f" ORDER BY {table_cfg.order_by}" if table_cfg.order_by else ""

        page = max(query.page, 1)
        page_size = query.page_size or table_cfg.page_size
        offset = (page - 1) * page_size

        total_rows = self._query(f'SELECT COUNT(*) AS n FROM "{table}"{where_sql}')
        total = int(_as_float(total_rows[0].get("n"))) if total_rows else 0
        data_rows = self._query(
            f'SELECT {col_list} FROM "{table}"{where_sql}{order_sql} '
            f"LIMIT {page_size} OFFSET {offset}"
        )
        return DetailRowsResponse(
            columns=columns,
            rows=[{c.field: _json_safe(r.get(c.field)) for c in table_cfg.columns}
                  for r in data_rows],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_incidents(self) -> IncidentsResponse:
        # Config-driven incidents not yet wired; SOC view is off by default.
        return IncidentsResponse.empty()


def _as_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _json_safe(value: Any) -> Any:
    """Coerce DuckDB scalars (datetime/date) to JSON-serializable values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
