from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv as _load_dotenv

_load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.models import HealthResponse
from app.api.routers.auth import router as auth_router
from app.api.routers.admin import router as admin_router
from app.api.routers.templates import router as templates_router
from app.api.routers.sources import router as sources_router
from app.api.routers.asins import router as asins_router
from app.api.routers.runs import router as runs_router
from app.api.routers.sot import router as sot_router
from app.api.routers.content import router as content_router

app = FastAPI(
    title="Wayfair Template Auto-Fill API",
    version="5.0.0",
    description="Phase 5A — Dynamic Template Auto-Fill System",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(templates_router, prefix="/api")
app.include_router(sources_router, prefix="/api")
app.include_router(asins_router, prefix="/api")
app.include_router(runs_router, prefix="/api")
app.include_router(sot_router, prefix="/api")
app.include_router(content_router, prefix="/api")


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
async def health():
    return HealthResponse(status="ok", version="5.0.7")


# Serve frontend — index.html with no-cache, assets with long cache
_DIST = Path("frontend/dist")
if _DIST.exists():
    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(request: Request, full_path: str = ""):
        # API routes are handled above — only catch non-API paths here
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        # Asset files (hashed names) — let StaticFiles handle them
        asset_path = _DIST / full_path
        if full_path and asset_path.exists() and asset_path.is_file():
            return FileResponse(str(asset_path))
        # Everything else → index.html with no-cache so browser always gets fresh version
        response = FileResponse(str(_DIST / "index.html"))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response
