"""Incidents endpoint -- active incident queue."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.config import Cyber360Config
from core.dependencies import get_config, get_obo_token
from models.common import ApiResponse, build_meta
from models.incidents import IncidentsResponse
from providers import get_provider

router = APIRouter()


@router.get("/incidents")
async def get_incidents(
    config: Cyber360Config = Depends(get_config),
    token: str = Depends(get_obo_token),
) -> ApiResponse[IncidentsResponse]:
    provider = get_provider(config, token)
    data = await provider.get_incidents()

    return ApiResponse(
        data=data,
        meta=build_meta(
            provider.source,
            ["mv_vulnerability_mgmt", "mv_identity_access"],
            ["critical_cves_open", "kev_unpatched", "orphaned_accounts"],
        ),
    )
