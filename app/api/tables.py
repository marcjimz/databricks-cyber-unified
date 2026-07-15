"""Table data endpoints -- paginated drill-down tables.

GET /api/identity/accounts     -- account inventory
GET /api/vulnerability/findings -- vulnerability findings queue
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from core.config import Cyber360Config
from core.dependencies import get_config, get_obo_token
from models.common import ApiResponse, Paginated, build_meta
from models.identity import AccountRow, AccountsQuery
from models.vulnerability import FindingRow, FindingsQuery
from providers import get_provider

router = APIRouter()


@router.get("/identity/accounts")
async def identity_accounts(
    status: str | None = Query(None),
    privileged: bool | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    config: Cyber360Config = Depends(get_config),
    token: str = Depends(get_obo_token),
) -> ApiResponse[Paginated[AccountRow]]:
    provider = get_provider(config, token)

    try:
        data = await provider.get_accounts(AccountsQuery(
            status=status,
            privileged=privileged,
            page=page,
            page_size=page_size,
        ))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return ApiResponse(
        data=data,
        meta=build_meta(
            provider.source,
            ["mv_identity_access"],
            ["orphaned_accounts", "dormant_admin_accounts"],
        ),
    )


@router.get("/vulnerability/findings")
async def vulnerability_findings(
    severity: str | None = Query(None),
    kev_only: bool = Query(False, alias="kevOnly"),
    sla_breached_only: bool = Query(False, alias="slaBreachedOnly"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    config: Cyber360Config = Depends(get_config),
    token: str = Depends(get_obo_token),
) -> ApiResponse[Paginated[FindingRow]]:
    provider = get_provider(config, token)

    try:
        data = await provider.get_findings(FindingsQuery(
            severity=severity,
            kev_only=kev_only,
            sla_breached_only=sla_breached_only,
            page=page,
            page_size=page_size,
        ))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return ApiResponse(
        data=data,
        meta=build_meta(
            provider.source,
            ["mv_vulnerability_mgmt"],
            ["critical_cves_open", "high_cves_open", "kev_unpatched"],
        ),
    )
