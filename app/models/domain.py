"""Domain drill-down response models."""

from __future__ import annotations

from pydantic import BaseModel

from core.config import RagStatus
from models.common import Kpi, TrendPoint


class BreakdownItem(BaseModel):
    name: str
    value: float


class DomainMetricsResponse(BaseModel):
    key: str
    label: str
    status: RagStatus
    kpis: list[Kpi]
    trends: dict[str, list[TrendPoint]]                # named trend series
    breakdowns: dict[str, list[BreakdownItem]]          # named breakdown charts
