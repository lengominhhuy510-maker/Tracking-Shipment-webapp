"""ETA recompute service (Spec §6.3, IC§5.1) — engine + DB + broadcast glue.

``recompute_eta(session, shipment_id)`` is the frozen signature TASK-04's AIS
worker calls per position message; the Agent A tool (TASK-08) wraps it with its
own session.

Forward-reference: ``geocode_port`` (app/services/geocode.py) is created by
TASK-07 which runs AFTER this task — the import is guarded; while absent every
recompute returns ``skipped_reason="no_pod_coords"`` (same pattern TASK-04 uses
for recompute_eta itself).

In-memory per-shipment state (module-level, reset on restart — acceptable for
single-process MVP, decision 0003): debounce timestamps, SOG sliding windows,
and the arrival-detector "first time condition held" marker (IC§0.3).
"""

import logging
from collections import deque
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.eta_engine import EnvInput, ETAComputeResult, ETAInput, compute_eta
from app.services.broadcast import (
    broadcast_deviation_alert,
    broadcast_eta_update,
    broadcast_status_change_suggested,
)
from app.db.models import EnvConditions, EtaHistory, Shipment

try:
    from app.services.geocode import geocode_port
except ImportError:  # TASK-07 not implemented yet — treat as "no POD coords".
    geocode_port = None

logger = logging.getLogger(__name__)

KM_PER_NM = 1.852
ARRIVAL_HOLD_MINUTES = 30

_last_recompute_at: dict[int, datetime] = {}
_sog_windows: dict[int, deque[float]] = {}
_arrival_first_seen: dict[int, datetime] = {}


def reset_state() -> None:
    """Clear in-memory debounce/window/arrival state (tests, worker restart)."""
    _last_recompute_at.clear()
    _sog_windows.clear()
    _arrival_first_seen.clear()


def _pod_coords(pod: str) -> tuple[float, float] | None:
    if geocode_port is None:
        return None
    geocoded = geocode_port(pod)
    if geocoded is None:
        return None
    lat, lon, _un_locode = geocoded
    return lat, lon


async def _check_arrival(shipment_id: int, result: ETAComputeResult, now: datetime) -> None:
    """IC§0.3 on_sea→arrived suggestion: within ARRIVAL_RADIUS_KM of POD and
    SOG below minimum held >=30 minutes. System only SUGGESTS — a human
    confirms via PATCH (TASK-03)."""
    if result.distance_remaining_nm is None or result.avg_sog_kn is None:
        _arrival_first_seen.pop(shipment_id, None)
        return
    radius_nm = settings.ARRIVAL_RADIUS_KM / KM_PER_NM
    in_radius_and_idle = (
        result.distance_remaining_nm <= radius_nm and result.avg_sog_kn < settings.SOG_MIN_KNOT
    )
    if not in_radius_and_idle:
        _arrival_first_seen.pop(shipment_id, None)
        return
    first_seen = _arrival_first_seen.setdefault(shipment_id, now)
    if now - first_seen >= timedelta(minutes=ARRIVAL_HOLD_MINUTES):
        await broadcast_status_change_suggested(
            shipment_id,
            {"suggested": "arrived", "reason": "tàu trong bán kính cảng đích, SOG~0"},
        )


async def recompute_eta(session: AsyncSession, shipment_id: int) -> ETAComputeResult | None:
    """Recompute both ETA tiers for one shipment; persist + broadcast.

    Returns the engine breakdown, or None when debounced.
    """
    now = datetime.now(UTC)

    last = _last_recompute_at.get(shipment_id)
    if last is not None and (now - last).total_seconds() < settings.ETA_RECOMPUTE_DEBOUNCE_SECONDS:
        return None
    _last_recompute_at[shipment_id] = now

    shipment = await session.get(Shipment, shipment_id)
    if shipment is None:
        logger.warning("recompute_eta: shipment %s not found", shipment_id)
        return None

    if shipment.current_lat is None or shipment.current_lon is None:
        return ETAComputeResult(skipped_reason="no_position")

    pod_coords = _pod_coords(shipment.pod)
    if pod_coords is None:
        return ETAComputeResult(skipped_reason="no_pod_coords")

    window = _sog_windows.setdefault(shipment_id, deque(maxlen=settings.AVG_SOG_WINDOW_MSGS))
    if shipment.current_sog is not None:
        window.append(shipment.current_sog)

    env_row = await session.get(EnvConditions, shipment_id)
    env = (
        EnvInput(
            wind_speed_kn=env_row.wind_speed_kn,
            wave_height_m=env_row.wave_height_m,
            current_speed_kn=env_row.current_speed_kn,
            current_direction_deg=env_row.current_direction_deg,
        )
        if env_row is not None
        else None
    )

    result = compute_eta(
        ETAInput(
            now=now,
            current_lat=shipment.current_lat,
            current_lon=shipment.current_lon,
            pod_lat=pod_coords[0],
            pod_lon=pod_coords[1],
            sog_window=list(window),
            cog=shipment.current_cog,
            eta_original=shipment.eta_original,
            atd=shipment.atd,
            env=env,
        )
    )

    await _check_arrival(shipment_id, result, now)

    if result.eta_tier2 is None:
        # sog_below_min: keep eta_current AND previous deviation-alert state.
        return result

    shipment.eta_current = result.eta_tier2

    last_row = (
        await session.execute(
            select(EtaHistory)
            .where(EtaHistory.shipment_id == shipment_id)
            .order_by(EtaHistory.recorded_at.desc(), EtaHistory.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    min_delta = timedelta(minutes=settings.ETA_HISTORY_MIN_DELTA_MINUTES)
    if last_row is None or abs(result.eta_tier2 - last_row.eta_value) > min_delta:
        session.add(
            EtaHistory(
                shipment_id=shipment_id,
                eta_value=result.eta_tier2,
                source="weather_adjusted",
                deviation_pct=result.deviation_pct,
            )
        )
    await session.commit()

    if (
        result.deviation_pct is not None
        and abs(result.deviation_pct) >= settings.ETA_DEVIATION_THRESHOLD_PCT
    ):
        await broadcast_deviation_alert(
            shipment_id,
            {
                "deviation_pct": result.deviation_pct,
                "eta_current": result.eta_tier2.isoformat(),
                "eta_original": shipment.eta_original.isoformat()
                if shipment.eta_original
                else None,
            },
        )

    await broadcast_eta_update(
        shipment_id,
        {
            "eta_tier1": result.eta_tier1.isoformat() if result.eta_tier1 else None,
            "eta_tier2": result.eta_tier2.isoformat(),
            "avg_sog_kn": result.avg_sog_kn,
            "distance_remaining_nm": result.distance_remaining_nm,
            "factors_applied": result.factors_applied,
            "deviation_pct": result.deviation_pct,
            "skipped_reason": result.skipped_reason,
        },
    )
    return result
