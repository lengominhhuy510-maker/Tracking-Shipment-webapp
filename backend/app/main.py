"""Minimal FastAPI app — TASK-00 scaffold."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import shipments

app = FastAPI(title="Shipment Tracking Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(shipments.router)


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# SPA fallback + StaticFiles: TASK-15
