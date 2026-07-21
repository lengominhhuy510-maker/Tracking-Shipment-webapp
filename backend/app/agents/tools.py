"""Agent A function-calling tools (IC§5.1) — plain async functions, TASK-08.

Each tool takes ``shipment_id`` and opens its OWN DB session via
``async_session_factory`` — the LLM never sees a session object. No framework
import here; registration happens in ``app/integrations/ag2_runner.py``.
"""

import logging
from datetime import UTC, datetime

from app.agents.schemas import (
    ETAComputeResult,
    ResearchFindingOut,
    ShipmentStateView,
    TideWindowResult,
)
from app.config import settings
from app.core.tide import eta_in_tidal_window
from app.db.base import async_session_factory
from app.db.models import EnvConditions, Shipment
from app.schemas.shipment import EnvConditionsOut
from app.services import eta_service
from app.services.geocode import geocode_port

logger = logging.getLogger(__name__)


def _locode(port: str) -> str | None:
    geocoded = geocode_port(port)
    if geocoded is None and port.split():
        # Stored port strings may be "SGSIN Singapore" — retry the locode prefix.
        geocoded = geocode_port(port.split()[0])
    return geocoded[2] if geocoded is not None else None


def _route_key(pol: str, pod: str) -> str | None:
    """Normalized POL-POD pair, e.g. ``SGSIN-VNCLI`` (§6.3d)."""
    pol_code = _locode(pol)
    pod_code = _locode(pod)
    if pol_code is None or pod_code is None:
        return None
    return f"{pol_code}-{pod_code}"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


async def get_shipment_state(shipment_id: int) -> ShipmentStateView:
    """Nạp state mới nhất từ DB: vị trí, SOG/COG, eta_original/current, atd,
    status, env_conditions, route_key. KHÔNG nạp transcript cũ (§6.4 stateless)."""
    async with async_session_factory() as session:
        shipment = await session.get(Shipment, shipment_id)
        if shipment is None:
            raise ValueError(f"shipment {shipment_id} not found")
        env = await session.get(EnvConditions, shipment_id)
        return ShipmentStateView(
            shipment_id=shipment.id,
            bl_number=shipment.bl_number,
            vessel_name=shipment.vessel_name,
            status=shipment.status,
            pol=shipment.pol,
            pod=shipment.pod,
            route_key=_route_key(shipment.pol, shipment.pod),
            current_lat=shipment.current_lat,
            current_lon=shipment.current_lon,
            sog=shipment.current_sog,
            cog=shipment.current_cog,
            eta_original=shipment.eta_original,
            eta_current=shipment.eta_current,
            atd=shipment.atd,
            env=EnvConditionsOut.model_validate(env) if env is not None else None,
        )


async def recompute_eta(shipment_id: int) -> ETAComputeResult:
    """Chạy ETA Engine Tầng 1+2 (§6.3, thuần code). Trả breakdown:
    {eta_tier1, eta_tier2, avg_sog_kn, distance_remaining_nm, factors_applied,
    skipped_reason, deviation_pct} — LLM thấy được VÌ SAO ra con số.
    Dấu deviation: dương=trễ, âm=sớm (§6.3)."""
    async with async_session_factory() as session:
        result = await eta_service.recompute_eta(session, shipment_id)
    if result is None:
        return ETAComputeResult(skipped_reason="debounced")
    return result


async def get_tide_window(shipment_id: int) -> TideWindowResult:
    """Đọc env_conditions.tide_extremes (KHÔNG gọi StormGlass — quota do cron
    quản, §6.6). Trả {extremes, eta_falls_in_window, station_name,
    data_age_hours} — kèm tuổi dữ liệu để agent tự nêu nhãn 'có thể trễ'."""
    async with async_session_factory() as session:
        shipment = await session.get(Shipment, shipment_id)
        if shipment is None:
            raise ValueError(f"shipment {shipment_id} not found")
        env = await session.get(EnvConditions, shipment_id)

    extremes = list(env.tide_extremes) if env is not None and env.tide_extremes else []
    eta_current = _as_utc(shipment.eta_current)
    fetched_at = _as_utc(env.tide_fetched_at) if env is not None else None
    return TideWindowResult(
        extremes=extremes,
        eta_falls_in_window=eta_in_tidal_window(eta_current, extremes, settings.TIDAL_WINDOW_HOURS),
        station_name=env.tide_station_name if env is not None else None,
        data_age_hours=(
            (datetime.now(UTC) - fetched_at).total_seconds() / 3600
            if fetched_at is not None
            else None
        ),
    )


async def request_research(shipment_id: int, focus: str | None = None) -> ResearchFindingOut:
    """Kích vòng A↔B (TASK-09). focus = hướng search cụ thể khi A yêu cầu search
    lại (VD 'chỉ eo Malacca 48h tới'). Check cache route_key TTL TRƯỚC khi gọi
    Agent B thật (§6.3d) — cache hit trả thẳng, không tốn search quota."""
    # Lazy import: research_service imports ``_route_key`` from this module.
    from app.services import research_service

    return await research_service.request_research(shipment_id, focus)
