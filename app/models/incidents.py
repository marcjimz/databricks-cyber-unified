"""Incident response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class IncidentRecord(BaseModel):
    uid: str
    priority: Literal["P1", "P2", "P3", "P4"]
    label: Literal["Critical", "High", "Medium", "Low"]
    domain: str
    status: Literal["open", "investigating", "contained", "resolved"]
    mttr_hours: float
    opened_time: int  # epoch millis
    title: str


class IncidentSeverityCounts(BaseModel):
    P1: int = 0
    P2: int = 0
    P3: int = 0
    P4: int = 0


class IncidentMttr(BaseModel):
    P1: str = ""
    P2: str = ""
    P3: str = ""
    P4: str = ""


class IncidentsResponse(BaseModel):
    active: list[IncidentRecord]
    open_counts: IncidentSeverityCounts
    mttr: IncidentMttr
