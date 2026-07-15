"""Common Pydantic models shared across API responses.

Port of the TypeScript contracts.ts types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

from core.config import RagStatus, TrendDirection

T = TypeVar("T")


class ResponseMeta(BaseModel):
    """Provenance metadata attached to every API response."""
    generated_at: str
    source: str  # "seed" | "databricks"
    metric_views: list[str]
    measures: list[str]


class ApiResponse(BaseModel, Generic[T]):
    """Standard API response wrapper with provenance."""
    data: T
    meta: ResponseMeta


class KpiLineage(BaseModel):
    """Lineage info for a KPI -- links to metric view definition."""
    measure: str
    expression: str
    comment: str


class TrendInfo(BaseModel):
    direction: TrendDirection
    label: str


class KpiChange(BaseModel):
    """Period-over-period change for a KPI, driven by the reporting-period
    selector (30/60/90 days). Rendered as the "Change: ..." line on the card,
    taking precedence over the static ``trend`` when present."""
    label: str                       # e.g. "+1.2 pts", "-3d", "+142", "No change"
    arrow: TrendDirection
    tone: str                        # "positive" | "negative" | "neutral"


class Kpi(BaseModel):
    """A single key performance indicator."""
    key: str
    label: str
    value: str       # pre-formatted: "99.2%", "142", "12.3d"
    raw: float       # raw numeric value
    status: RagStatus
    caption: str = ""
    trend: TrendInfo | None = None
    change: KpiChange | None = None
    lineage: KpiLineage


class TrendPoint(BaseModel):
    """A single point in a time-series trend."""
    day: str  # ISO date string
    values: dict[str, float]  # measure_name -> value


class Paginated(BaseModel, Generic[T]):
    """Paginated list response."""
    rows: list[T]
    total: int
    page: int
    page_size: int


def build_meta(source: str, metric_views: list[str], measures: list[str]) -> ResponseMeta:
    """Build a ResponseMeta with current timestamp."""
    return ResponseMeta(
        generated_at=datetime.utcnow().isoformat() + "Z",
        source=source,
        metric_views=metric_views,
        measures=measures,
    )
