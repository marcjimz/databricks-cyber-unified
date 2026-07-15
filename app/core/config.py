"""Cyber360 configuration loader and Pydantic models.

Loads cyber360.yaml, resolves ${ENV_VAR} placeholders from environment,
and provides typed access to all configuration sections.
"""

from __future__ import annotations

import os
import re
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RagStatus(str, Enum):
    green = "green"
    amber = "amber"
    red = "red"


class RagGoal(str, Enum):
    higher = "higher"
    lower = "lower"


class MeasureFormat(str, Enum):
    percent = "percent"
    count = "count"
    days = "days"
    hours = "hours"
    score = "score"


class TrendDirection(str, Enum):
    up = "up"
    down = "down"
    flat = "flat"


# ---------------------------------------------------------------------------
# Config Models
# ---------------------------------------------------------------------------

class OrgConfig(BaseModel):
    name: str
    logo_path: str = "org-logo.png"


class DataSourceConfig(BaseModel):
    catalog: str = "cyber360"
    schema_: str = Field("posture", alias="schema")
    warehouse_id: str = ""
    provider: str = "seed"

    model_config = {"populate_by_name": True}


class LakebaseSyncedTablesConfig(BaseModel):
    """Names of the read-only aggregate tables produced by the reverse-ETL sync."""
    daily: str = "agg_daily_synced"
    rollup: str = "agg_rollup_synced"


class LakebaseStateTablesConfig(BaseModel):
    """Names of the app-owned read-write state tables."""
    preferences: str = "cyber360_preferences"
    chats: str = "cyber360_chats"
    sessions: str = "cyber360_sessions"


class LakebaseConfig(BaseModel):
    enabled: bool = False
    instance_name: str = ""
    database_name: str = "cyber360"
    # Postgres schema the app SERVICE PRINCIPAL owns for its read-write state
    # tables. The SP has database-level CREATE (from the bound Lakebase resource's
    # CAN_CONNECT_AND_CREATE), so it creates and owns this schema itself -- no
    # external grant required. Kept separate from the read-only synced-aggregate
    # schema (data_source.schema), which the SP only has SELECT on.
    app_schema: str = "cyber360_app"
    synced_tables: LakebaseSyncedTablesConfig = LakebaseSyncedTablesConfig()
    state_tables: LakebaseStateTablesConfig = LakebaseStateTablesConfig()


class DataLoadingConfig(BaseModel):
    enabled: bool = True
    target_catalog: str = "cyber360"
    target_schema: str = "posture"
    load_synthetic: bool = True


class FeaturesConfig(BaseModel):
    genie_enabled: bool = True
    soc_view_enabled: bool = True
    theme_toggle: bool = True
    lineage_popover: bool = True


class TrendConfig(BaseModel):
    direction: TrendDirection
    label: str


class DimensionConfig(BaseModel):
    name: str
    expression: str
    comment: str = ""


class MeasureConfig(BaseModel):
    name: str
    label: str
    expression: str
    comment: str = ""
    format: MeasureFormat = MeasureFormat.count
    percent_digits: int = 0
    goal: RagGoal = RagGoal.higher
    green: float | None = None
    amber: float | None = None
    fixed_status: RagStatus | None = None
    caption: str = ""
    trend: TrendConfig | None = None


class MetricViewConfig(BaseModel):
    name: str
    source_table: str
    comment: str = ""
    dimensions: list[DimensionConfig] = []
    measures: list[MeasureConfig] = []


class GenieConfig(BaseModel):
    space_id: str = ""
    embed_url: str = ""
    starters: list[str] = []


class DomainHealthConfig(BaseModel):
    score_measures: list[str] = []
    highlights: list[str] = []


class DomainConfig(BaseModel):
    key: str
    label: str
    short: str
    icon: str
    description: str = ""
    genie: GenieConfig = GenieConfig()
    health: DomainHealthConfig = DomainHealthConfig()
    metric_view: MetricViewConfig


class TopLineKpiConfig(BaseModel):
    domain: str
    measure: str
    caption: str = ""
    trend: TrendConfig | None = None


class Cyber360Config(BaseModel):
    """Root configuration model for the Cyber360 dashboard."""

    org: OrgConfig
    data_source: DataSourceConfig
    lakebase: LakebaseConfig = LakebaseConfig()
    data_loading: DataLoadingConfig = DataLoadingConfig()
    features: FeaturesConfig = FeaturesConfig()
    top_line_kpis: list[TopLineKpiConfig] = []
    domains: list[DomainConfig] = []

    # ── Lookup helpers ──

    def get_domain(self, key: str) -> DomainConfig | None:
        return next((d for d in self.domains if d.key == key), None)

    def get_measure(self, domain_key: str, measure_name: str) -> MeasureConfig | None:
        domain = self.get_domain(domain_key)
        if not domain:
            return None
        return next((m for m in domain.metric_view.measures if m.name == measure_name), None)

    def find_measure(self, measure_name: str) -> tuple[DomainConfig, MeasureConfig] | None:
        for domain in self.domains:
            for measure in domain.metric_view.measures:
                if measure.name == measure_name:
                    return domain, measure
        return None

    def domain_keys(self) -> list[str]:
        return [d.key for d in self.domains]


# ---------------------------------------------------------------------------
# RAG / formatting helpers (shared between backend and frontend logic)
# ---------------------------------------------------------------------------

def rag_for_measure(measure: MeasureConfig, raw: float) -> RagStatus:
    """Compute RAG status for a measure value."""
    if measure.fixed_status is not None:
        return measure.fixed_status
    if measure.green is None or measure.amber is None:
        return RagStatus.green
    if measure.goal == RagGoal.higher:
        if raw >= measure.green:
            return RagStatus.green
        if raw >= measure.amber:
            return RagStatus.amber
        return RagStatus.red
    else:  # lower
        if raw <= measure.green:
            return RagStatus.green
        if raw <= measure.amber:
            return RagStatus.amber
        return RagStatus.red


def rollup_status(statuses: list[RagStatus]) -> RagStatus:
    """Roll up a list of statuses to the worst."""
    if RagStatus.red in statuses:
        return RagStatus.red
    if RagStatus.amber in statuses:
        return RagStatus.amber
    return RagStatus.green


def format_measure_value(measure: MeasureConfig, raw: float) -> str:
    """Format a raw measure value for display."""
    fmt = measure.format
    if fmt == MeasureFormat.percent:
        digits = measure.percent_digits
        return f"{raw:.{digits}f}%"
    elif fmt == MeasureFormat.count:
        return f"{int(round(raw)):,}"
    elif fmt == MeasureFormat.days:
        return f"{raw:.1f}d"
    elif fmt == MeasureFormat.hours:
        return f"{raw:.1f}h"
    elif fmt == MeasureFormat.score:
        return f"{raw:.0f}"
    return str(raw)


# ---------------------------------------------------------------------------
# Period-over-period change (reporting-period selector: 30 / 60 / 90 days)
# ---------------------------------------------------------------------------

COMPARISON_PERIODS: tuple[int, ...] = (30, 60, 90)


def normalize_period(period: int | None) -> int:
    """Clamp an arbitrary period to the supported {30, 60, 90} set (default 30)."""
    return period if period in COMPARISON_PERIODS else 30


def _hash_unit(s: str) -> float:
    """Stable 0..1 hash (FNV-1a) so synthesized period deltas are deterministic
    per demo -- mirrors the TypeScript reference exactly."""
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return (h & 0xFFFFFFFF) / 4294967296


def build_change(measure: MeasureConfig, raw: float, period: int) -> dict[str, str]:
    """Build a KPI's period-over-period change over the selected reporting
    period vs. the prior period of the same length.

    Returns a plain dict (``label``/``arrow``/``tone``) that callers wrap in a
    ``KpiChange`` model -- kept dict-shaped here to avoid a models<->config
    import cycle. This is the SEED path: the seed dataset is a single snapshot,
    so the prior period is synthesized deterministically (larger windows move
    more) for a demo that is stable across reloads. A real provider reads the
    measure over both windows instead. The label carries no period suffix --
    the selected reporting period is already shown in the header control.
    """
    period = normalize_period(period)
    scale = 0.06 if period == 30 else 0.10 if period == 60 else 0.15
    signed = (_hash_unit(f"{measure.name}:{period}") * 2 - 1) * scale
    raw_change = raw * signed

    is_count = measure.format in (MeasureFormat.count, MeasureFormat.score)
    magnitude = round(raw_change) if is_count else round(raw_change * 10) / 10
    return _format_change(measure, magnitude)


def _format_change(measure: MeasureConfig, magnitude: float) -> dict[str, str]:
    """Format a numeric period delta into the KpiChange contract shape.

    Shared by the seed (synthesized) and Lakebase (real agg_rollup) paths so the
    label/arrow/tone semantics stay identical regardless of data source.
    """
    arrow = (
        TrendDirection.up if magnitude > 0
        else TrendDirection.down if magnitude < 0
        else TrendDirection.flat
    )

    # Favorable if the movement pushes toward the measure's goal direction.
    if arrow == TrendDirection.flat:
        tone = "neutral"
    else:
        improving = (measure.goal == RagGoal.higher) == (magnitude > 0)
        tone = "positive" if improving else "negative"

    sign = "+" if magnitude > 0 else ""
    if measure.format == MeasureFormat.percent:
        label = f"{sign}{magnitude:.1f} pts"
    elif measure.format == MeasureFormat.days:
        label = f"{sign}{magnitude:.1f}d"
    elif measure.format == MeasureFormat.hours:
        label = f"{sign}{magnitude:.1f}h"
    else:
        label = f"{sign}{int(magnitude):,}"

    return {
        "label": "No change" if arrow == TrendDirection.flat else label,
        "arrow": arrow.value,
        "tone": tone,
    }


# ---------------------------------------------------------------------------
# YAML loader with env var resolution
# ---------------------------------------------------------------------------

# Supports ${VAR} and ${VAR:-default} (default used when the env var is unset
# OR set-but-empty, matching POSIX shell semantics).
_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _resolve_env_vars(obj: Any) -> Any:
    """Recursively resolve ${VAR} / ${VAR:-default} placeholders from environment."""
    if isinstance(obj, str):
        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            default = match.group(2)
            value = os.environ.get(var_name, "")
            if not value and default is not None:
                return default
            return value
        return _ENV_VAR_RE.sub(_replace, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


def load_config(path: Path | str | None = None) -> Cyber360Config:
    """Load and validate cyber360.yaml from the given path."""
    if path is None:
        path = Path(__file__).parent.parent / "cyber360.yaml"
    path = Path(path)

    with open(path) as f:
        raw = yaml.safe_load(f)

    resolved = _resolve_env_vars(raw)
    return Cyber360Config.model_validate(resolved)
