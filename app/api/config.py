"""Config endpoint -- serves sanitized dashboard config to the frontend.

Exposes org info, features, domains (with measures/thresholds), and
top-line KPI references. Internal fields (source_table, warehouse_id)
are stripped for security.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.config import CyberUnifiedConfig
from core.dependencies import get_config
from models.common import build_meta

router = APIRouter()


@router.get("/config")
async def get_dashboard_config(config: CyberUnifiedConfig = Depends(get_config)):
    """Return the dashboard configuration for the frontend."""
    domains = []
    for d in config.domains:
        measures = []
        for m in d.metric_view.measures:
            measures.append({
                "name": m.name,
                "label": m.label,
                "expression": m.expression,
                "comment": m.comment,
                "format": m.format.value,
                "percentDigits": m.percent_digits,
                "goal": m.goal.value,
                "green": m.green,
                "amber": m.amber,
                "fixedStatus": m.fixed_status.value if m.fixed_status else None,
                "caption": m.caption,
                "trend": {"direction": m.trend.direction.value, "label": m.trend.label} if m.trend else None,
            })

        genie = {
            "spaceId": d.genie.space_id,
            "embedUrl": d.genie.embed_url,
            "starters": d.genie.starters,
        }

        detail_table = {
            "label": d.detail_table.label,
            "orderBy": d.detail_table.order_by,
            "pageSize": d.detail_table.page_size,
            "columns": [
                {"field": c.field, "label": c.label or c.field, "format": c.format}
                for c in d.detail_table.columns
            ],
            "filters": [
                {"key": f.key, "label": f.label or f.key}
                for f in d.detail_table.filters
            ],
        }

        domains.append({
            "key": d.key,
            "label": d.label,
            "short": d.short,
            "icon": d.icon,
            "description": d.description,
            "genie": genie,
            "health": {
                "scoreMeasures": d.health.score_measures,
                "highlights": d.health.highlights,
            },
            "metricView": {
                "name": d.metric_view.name,
                "comment": d.metric_view.comment,
                "measures": measures,
            },
            "detailTable": detail_table,
        })

    top_line_kpis = []
    for t in config.top_line_kpis:
        top_line_kpis.append({
            "domain": t.domain,
            "measure": t.measure,
            "caption": t.caption,
            "trend": {"direction": t.trend.direction.value, "label": t.trend.label} if t.trend else None,
        })

    data = {
        "org": {
            "name": config.org.name,
            "logoPath": config.org.logo_path,
        },
        "features": {
            "genieEnabled": config.features.genie_enabled,
            "socViewEnabled": config.features.soc_view_enabled,
            "themeToggle": config.features.theme_toggle,
            "lineagePopover": config.features.lineage_popover,
        },
        "topLineKpis": top_line_kpis,
        "domains": domains,
    }

    # Wrap in the standard {data, meta} envelope so the frontend fetcher
    # (which returns json.data) resolves correctly -- same contract as
    # /api/metrics/*. Provenance here is the config file itself.
    metric_views = [d.metric_view.name for d in config.domains]
    measures = [m.name for d in config.domains for m in d.metric_view.measures]
    return {
        "data": data,
        "meta": build_meta(
            source=config.data_source.provider,
            metric_views=metric_views,
            measures=measures,
        ).model_dump(),
    }
