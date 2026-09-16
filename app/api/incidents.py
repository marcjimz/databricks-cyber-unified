"""Incidents endpoint -- active incident queue.

Gated by ``features.soc_view_enabled``. When the SOC view is off (the default),
this returns an empty response rather than demo data. A config-driven incident
source can be wired later; there is no hardcoded incident list.
"""

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
    if not config.features.soc_view_enabled:
        return ApiResponse(
            data=IncidentsResponse.empty(),
            meta=build_meta(config.data_source.provider, [], []),
        )

    provider = get_provider(config, token)
    data = await provider.get_incidents()
    return ApiResponse(
        data=data,
        meta=build_meta(provider.source, [], []),
    )
