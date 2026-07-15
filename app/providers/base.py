"""DataProvider protocol -- defines the contract for data access."""

from __future__ import annotations

from typing import Protocol

from models.common import Paginated
from models.domain import DomainMetricsResponse
from models.identity import AccountRow, AccountsQuery
from models.incidents import IncidentsResponse
from models.scorecard import ScorecardResponse
from models.vulnerability import FindingRow, FindingsQuery


class DataProvider(Protocol):
    """Contract for data providers (seed, databricks)."""

    source: str  # "seed" | "databricks"

    async def get_scorecard(self) -> ScorecardResponse: ...

    async def get_domain_metrics(self, domain_key: str) -> DomainMetricsResponse: ...

    async def get_accounts(self, query: AccountsQuery) -> Paginated[AccountRow]: ...

    async def get_findings(self, query: FindingsQuery) -> Paginated[FindingRow]: ...

    async def get_incidents(self) -> IncidentsResponse: ...
