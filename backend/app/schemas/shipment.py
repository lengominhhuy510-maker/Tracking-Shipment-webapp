"""Pydantic schemas for shipments API (IC§4.4 + Out models mapping DB columns 1-1).

datetime fields are tz-aware UTC (IC§15) — naive datetimes rejected.
"""

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

Incoterm = Literal["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]


def _reject_naive(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        raise ValueError("datetime phải tz-aware UTC (IC§15)")
    return v


class ShipmentCreate(BaseModel):
    bl_number: str
    container_no: str  # normalize + ISO 6346 validated at route layer (400, not 422)
    shipment_direction: Literal["import", "export"]
    incoterm: Incoterm
    carrier: str
    vessel_name: str
    voyage_no: str
    pol: str
    pod: str
    eta_original: datetime | None = None
    imo: str | None = Field(None, pattern=r"^\d{7}$")
    mmsi: str | None = Field(None, pattern=r"^\d{9}$")

    _tz = field_validator("eta_original")(_reject_naive)


class ShipmentPatch(BaseModel):
    """Whitelist-only editable fields (IC§3.2). Forbidden fields caught at route → 400."""

    model_config = ConfigDict(extra="allow")  # extras detected in route → 400 IMMUTABLE_FIELD

    eta_original: datetime | None = None
    atd: datetime | None = None
    pol: str | None = None
    pod: str | None = None
    status: Literal["new", "on_sea", "arrived", "delivered"] | None = None
    bl_number: str | None = None
    carrier: str | None = None

    _tz_eta = field_validator("eta_original")(_reject_naive)
    _tz_atd = field_validator("atd")(_reject_naive)


class ResolveManualIn(BaseModel):
    imo: str = Field(pattern=r"^\d{7}$")
    mmsi: str = Field(pattern=r"^\d{9}$")


class LegOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int
    leg_no: int
    vessel_name: str
    voyage_no: str | None
    imo: str | None
    mmsi: str | None
    imo_resolved_via: str | None
    pol: str
    pod: str
    onboarding_status: str
    onboarding_error: str | None
    is_active_leg: bool
    superseded_at: datetime | None
    created_at: datetime


class EtaHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int
    eta_value: datetime
    source: str
    deviation_pct: float | None
    note: str | None
    recorded_at: datetime


class TrailPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lat: float
    lon: float
    sog: float | None
    recorded_at: datetime


class EnvConditionsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shipment_id: int
    wind_speed_kn: float | None
    wave_height_m: float | None
    current_speed_kn: float | None
    current_direction_deg: float | None
    weather_fetched_at: datetime | None
    tide_extremes: list | None
    tide_station_name: str | None
    tide_station_distance_km: float | None
    tide_fetched_at: datetime | None


class ShipmentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bl_number: str
    container_no: str
    incoterm: str
    shipment_direction: str
    carrier: str
    vessel_name: str
    voyage_no: str | None
    pol: str
    pod: str
    status: str
    monitoring_mode: str
    onboarding_status: str
    onboarding_error: str | None
    eta_current: datetime | None
    current_lat: float | None
    current_lon: float | None
    current_sog: float | None
    current_cog: float | None
    position_updated_at: datetime | None


class ShipmentDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bl_number: str
    container_no: str
    incoterm: str
    shipment_direction: str
    carrier: str
    vessel_name: str
    imo: str | None
    imo_resolved_via: str | None
    mmsi: str | None
    voyage_no: str | None
    pol: str
    pod: str
    eta_original: datetime | None
    eta_original_source: str | None
    eta_current: datetime | None
    atd: datetime | None
    status: str
    shipment_type: str
    onboarding_status: str
    onboarding_error: str | None
    monitoring_mode: str
    current_lat: float | None
    current_lon: float | None
    current_sog: float | None
    current_cog: float | None
    position_updated_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    legs: list[LegOut] = []
    env: EnvConditionsOut | None = Field(
        None, validation_alias=AliasChoices("env", "env_conditions")
    )
    recent_eta_history: list[EtaHistoryOut] = []
