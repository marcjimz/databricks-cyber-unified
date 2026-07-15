"""Metrics endpoints -- scorecard and per-domain drill-down.

GET /api/metrics/scorecard  -- top-line KPIs + domain health
GET /api/metrics/{domain_key} -- domain-specific KPIs, trends, breakdowns
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from core.config import Cyber360Config, normalize_period
from core.dependencies import get_config, get_obo_token
from models.common import ApiResponse, build_meta
from models.domain import DomainMetricsResponse
from models.scorecard import ScorecardResponse
from providers import get_provider

router = APIRouter()


@router.get("/metrics/scorecard")
async def metrics_scorecard(
    period: int = Query(30, description="Reporting period in days (30, 60, or 90)"),
    config: Cyber360Config = Depends(get_config),
    token: str = Depends(get_obo_token),
) -> ApiResponse[ScorecardResponse]:
    provider = get_provider(config, token)
    data = await provider.get_scorecard(normalize_period(period))

    # Collect provenance from config
    measures = [t.measure for t in config.top_line_kpis]
    metric_views = list({
        config.get_domain(t.domain).metric_view.name
        for t in config.top_line_kpis
        if config.get_domain(t.domain)
    })

    return ApiResponse(
        data=data,
        meta=build_meta(provider.source, metric_views, measures),
    )


@router.get("/metrics/{domain_key}")
async def metrics_domain(
    domain_key: str,
    period: int = Query(30, description="Reporting period in days (30, 60, or 90)"),
    config: Cyber360Config = Depends(get_config),
    token: str = Depends(get_obo_token),
) -> ApiResponse[DomainMetricsResponse]:
    domain = config.get_domain(domain_key)
    if not domain:
        raise HTTPException(status_code=404, detail=f"Domain '{domain_key}' not found in config")

    provider = get_provider(config, token)

    try:
        data = await provider.get_domain_metrics(domain_key, normalize_period(period))
    except PermissionError as e:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PERMISSION_DENIED",
                "message": str(e),
                "domain": domain_key,
                "metric_view": domain.metric_view.name,
            },
        )

    mv = domain.metric_view
    return ApiResponse(
        data=data,
        meta=build_meta(
            provider.source,
            [mv.name],
            [m.name for m in mv.measures],
        ),
    )
