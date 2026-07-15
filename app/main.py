"""Cyber360 Dashboard -- FastAPI Application Entry Point.

Serves the React SPA and API endpoints for the Cyber360 cybersecurity
posture dashboard. Configuration is loaded from cyber360.yaml at startup.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.auth import OBOMiddleware
from core.config import load_config
from core.db import close_lakebase_pool, init_lakebase_pool
from core.dependencies import set_global_config
from core.state import run_state_migrations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("cyber360")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifecycle: load config, init connections on startup; cleanup on shutdown."""
    config_path = Path(__file__).parent / "cyber360.yaml"
    logger.info("Loading config from %s", config_path)
    config = load_config(config_path)
    set_global_config(config)
    logger.info(
        "Config loaded: org=%s, provider=%s, domains=%s",
        config.org.name,
        config.data_source.provider,
        [d.key for d in config.domains],
    )

    # Initialize Lakebase pool if configured, then bootstrap app-owned state tables
    await init_lakebase_pool(config)
    await run_state_migrations(config)

    yield

    # Shutdown
    await close_lakebase_pool()
    logger.info("Cyber360 shutdown complete")


app = FastAPI(
    title="Cyber360 Dashboard",
    description="Unified Cybersecurity Posture Dashboard",
    version="0.1.0",
    lifespan=lifespan,
)

# OBO authentication middleware
app.add_middleware(OBOMiddleware)

# API routes (imported after app creation to avoid circular imports)
from api.config import router as config_router  # noqa: E402
from api.health import router as health_router  # noqa: E402
from api.incidents import router as incidents_router  # noqa: E402
from api.metrics import router as metrics_router  # noqa: E402
from api.tables import router as tables_router  # noqa: E402

app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(config_router, prefix="/api", tags=["config"])
app.include_router(metrics_router, prefix="/api", tags=["metrics"])
app.include_router(tables_router, prefix="/api", tags=["tables"])
app.include_router(incidents_router, prefix="/api", tags=["incidents"])

# Serve the React SPA -- registered AFTER the API routers so /api/* wins.
#
# The SPA is a single-page app: the server must return index.html for EVERY
# client-side route (/, /scorecard, /manager, /soc, /domain/:key) so React
# Router can take over. A plain StaticFiles(html=True) mount only serves
# index.html for the directory root and 404s on client routes (and on refresh /
# deep links), which is why the base page appeared to "not route". We instead:
#   1. mount the hashed build assets at /assets (long-cache immutable files),
#   2. serve real files that live at the dist root (favicon, logos) directly,
#   3. fall back to index.html for anything else -> React Router handles it.
_frontend_dist = Path(__file__).parent / "frontend" / "dist"
_spa_index = _frontend_dist / "index.html"
if _spa_index.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=str(_frontend_dist / "assets")),
        name="assets",
    )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve a real dist file when it exists, else the SPA index (client routing)."""
        # Unknown /api/* paths are genuine 404s, not SPA routes.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        if full_path:
            candidate = (_frontend_dist / full_path).resolve()
            # Guard against path traversal; only serve files inside dist.
            if (
                candidate.is_file()
                and _frontend_dist.resolve() in candidate.parents
            ):
                return FileResponse(str(candidate))
        return FileResponse(str(_spa_index))

    logger.info("Serving frontend SPA from %s", _frontend_dist)
else:
    logger.warning("Frontend dist not found at %s -- run 'make build' first", _frontend_dist)
