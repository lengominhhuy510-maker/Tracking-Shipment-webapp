"""FastAPI app — embeds AIS worker + trail snapshot via lifespan (Spec §3.1)."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api import shipments, ws
from app.api.deps import get_current_user
from app.auth import routes as auth_routes
from app.config import settings
from app.services import reasoning_service
from app.workers import ais_worker, tide_poll, trail_snapshot, weather_poll

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start background workers on startup; cancel them cleanly on shutdown."""
    tasks = [
        asyncio.create_task(ais_worker.run(), name="ais_worker"),
        asyncio.create_task(trail_snapshot.run(), name="trail_snapshot"),
        asyncio.create_task(weather_poll.run(), name="weather_poll"),
        asyncio.create_task(tide_poll.run(), name="tide_poll"),
        asyncio.create_task(reasoning_service.run_scheduler(), name="agent_a_scheduler"),
    ]
    logger.info("started %d background worker(s)", len(tasks))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        logger.info("background workers stopped")


app = FastAPI(title="Shipment Tracking Demo", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_JWT_SECRET,
    https_only=settings.COOKIE_SECURE,
    same_site="lax",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(shipments.router)
app.include_router(ws.router)


@app.get("/api/v1/health", dependencies=[Depends(get_current_user)])
async def health() -> dict[str, str]:
    return {"status": "ok"}


# TASK-15: frontend build tĩnh (Dockerfile COPY dist → /app/static).
_STATIC_DIR = Path("/app/static")

if (_STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")


# Catch-all SPA fallback — đăng ký SAU mọi router /api,/ws (route order quyết định).
@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str) -> FileResponse:
    if full_path in ("api", "ws") or full_path.startswith(("api/", "ws/")):
        raise HTTPException(status_code=404, detail="Not Found")
    if full_path:
        static_root = _STATIC_DIR.resolve()
        candidate = (_STATIC_DIR / full_path).resolve()
        if candidate.is_relative_to(static_root) and candidate.is_file():
            return FileResponse(candidate)
    index = _STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Frontend build not found")
    return FileResponse(index)
