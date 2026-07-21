"""FastAPI app — embeds AIS worker + trail snapshot via lifespan (Spec §3.1)."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api import proposals, shipments, ws
from app.api.deps import get_current_user
from app.auth import routes as auth_routes
from app.config import settings
from app.services import email_service, reasoning_service
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
        # exactly ONE email poller (§7.1 single-process model)
        asyncio.create_task(email_service.run(), name="email_poller"),
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
app.include_router(proposals.router)
app.include_router(ws.router)


@app.get("/api/v1/health", dependencies=[Depends(get_current_user)])
async def health() -> dict[str, str]:
    return {"status": "ok"}


# SPA fallback + StaticFiles: TASK-15
