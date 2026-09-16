"""DataProvider protocol -- defines the contract for data access.

Every method is domain-agnostic: providers read what to compute/return from the
config (measures, dimensions, detail_table), so adding a domain is config-only.
"""

from __future__ import annotations

from typing import Protocol

from models.detail import DetailQuery, DetailRowsResponse
from models.domain import DomainMetricsResponse
from models.incidents import IncidentsResponse
from models.scorecard import ScorecardResponse


class DataProvider(Protocol):
    """Contract for data providers (seed, metricview)."""

    source: str  # "seed" | "metricview"

    async def get_scorecard(self, period: int = 30) -> ScorecardResponse: ...

    async def get_domain_metrics(
        self, domain_key: str, period: int = 30
    ) -> DomainMetricsResponse: ...

    async def get_detail_rows(
        self, domain_key: str, query: DetailQuery
    ) -> DetailRowsResponse: ...

    async def get_incidents(self) -> IncidentsResponse: ...
