"""Generic, config-driven drill-down table endpoint.

GET /api/{domain}/rows -- a page of the domain's detail table.

There is ONE endpoint for every domain. What it returns is defined entirely by
the domain's ``detail_table:`` config block (columns, filters, sort): the
provider SELECTs those columns from the domain's ``source_table`` per-user (OBO).
Adding a drill-down table is a pure config edit -- no per-domain endpoint or row
model (the old /identity/accounts + /vulnerability/findings are gone).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from core.config import Cyber360Config
from core.dependencies import get_config, get_obo_token
from models.common import ApiResponse, build_meta
from models.detail import DetailQuery, DetailRowsResponse
from providers import get_provider

router = APIRouter()


@router.get("/{domain_key}/rows")
async def domain_rows(
    domain_key: str,
    filter: str | None = Query(None, description="One of the domain's configured filter keys"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    config: Cyber360Config = Depends(get_config),
    token: str = Depends(get_obo_token),
) -> ApiResponse[DetailRowsResponse]:
    domain = config.get_domain(domain_key)
    if not domain:
        raise HTTPException(status_code=404, detail=f"Unknown domain: {domain_key}")

    provider = get_provider(config, token)
    try:
        data = await provider.get_detail_rows(
            domain_key, DetailQuery(filter_key=filter, page=page, page_size=page_size)
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return ApiResponse(
        data=data,
        meta=build_meta(
            provider.source,
            [domain.metric_view.name],
            [c.field for c in domain.detail_table.columns],
        ),
    )
