"""Pydantic views the Agent A tools return (IC§4.3, IC§5.1 — TASK-08).

``ETAComputeResult`` is re-exported from the rule engine (TASK-05) so the LLM
tool layer and the engine share one breakdown shape — no parallel model.
"""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.core.eta_engine import ETAComputeResult
from app.schemas.shipment import EnvConditionsOut

__all__ = [
    "ETAComputeResult",
    "ResearchFindingOut",
    "ShipmentStateView",
    "TideWindowResult",
]


class ShipmentStateView(BaseModel):
    """Latest DB state of one shipment — no old transcript (§6.4 stateless)."""

    shipment_id: int
    bl_number: str
    vessel_name: str
    status: str
    pol: str
    pod: str
    route_key: str | None
    current_lat: float | None
    current_lon: float | None
    sog: float | None
    cog: float | None
    eta_original: datetime | None
    eta_current: datetime | None
    atd: datetime | None
    env: EnvConditionsOut | None

    @field_validator("eta_original", "eta_current", "atd")
    @classmethod
    def _assume_utc(cls, value: datetime | None) -> datetime | None:
        # SQLite (unit tests) returns naive datetimes; stored values are UTC.
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class TideWindowResult(BaseModel):
    """IC§5.1 get_tide_window — cached env_conditions read, never StormGlass."""

    extremes: list[dict[str, Any]] = Field(default_factory=list)
    eta_falls_in_window: bool | None
    station_name: str | None
    data_age_hours: float | None


class ResearchFindingOut(BaseModel):
    """IC§4.3 — one model for Agent B return AND the API response shape."""

    event: str
    relevance: Literal["cao", "trung_binh", "thap"]
    route_impact: str
    confidence: Literal["cao", "trung_binh", "thap"]
    sources: list[HttpUrl] = Field(min_length=1)
