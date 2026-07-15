"""Scorecard response models."""

from __future__ import annotations

from pydantic import BaseModel

from core.config import RagStatus
from models.common import Kpi


class ComplianceCounts(BaseModel):
    green: int
    amber: int
    red: int
    total: int


class DomainHealthHighlight(BaseModel):
    label: str
    value: str
    status: RagStatus


class DomainHealth(BaseModel):
    key: str
    label: str
    status: RagStatus
    highlights: list[DomainHealthHighlight]
    score: float  # 0-100 posture score
    compliance: ComplianceCounts


class ScorecardOrg(BaseModel):
    name: str
    caregivers: int = 0
    cyber_staff: int = 0


class ScorecardResponse(BaseModel):
    org: ScorecardOrg
    top_line_kpis: list[Kpi]
    domains: list[DomainHealth]
