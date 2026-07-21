"""Tide poll worker (Spec §6.6) — StormGlass, every TIDE_POLL_HOURS.

Sole producer of ``tidal_alert``. Geocodes each on-sea shipment's POD via the
local WPI table, fetches tide extremes under a 10-call/UTC-day quota, and
upserts the tide-owned fields of ``env_conditions``. Missing key or provider
failure keeps cached values and never crashes the app.

Quota is in-memory — valid only under the single-process constraint
(Decision 0003); a restart resets the count.
"""

import asyncio
import logging
from datetime import UTC, date, datetime

from sqlalchemy import select

from app.config import settings
from app.core.tide import eta_in_tidal_window, nearest_high_tide
from app.db.base import async_session_factory
from app.db.models import EnvConditions, Shipment
from app.integrations.errors import ExternalIntegrationError
from app.integrations.stormglass import fetch_tide
from app.services.broadcast import broadcast_tidal_alert
from app.services.geocode import geocode_port

logger = logging.getLogger(__name__)

_MAX_DAILY_CALLS = 10

_quota_day: date | None = None
_quota_calls = 0


def _utc_today() -> date:
    return datetime.now(UTC).date()


def reset_quota() -> None:
    global _quota_day, _quota_calls
    _quota_day = None
    _quota_calls = 0


def _try_consume_quota() -> bool:
    global _quota_day, _quota_calls
    today = _utc_today()
    if _quota_day != today:
        _quota_day = today
        _quota_calls = 0
    if _quota_calls >= _MAX_DAILY_CALLS:
        return False
    _quota_calls += 1
    return True


async def _poll_once() -> int:
    """Fetch + upsert tide data for eligible shipments; return update count."""
    if not settings.STORMGLASS_API_KEY:
        logger.warning("tide poll: thiếu STORMGLASS_API_KEY — bỏ qua chu kỳ, app vẫn chạy")
        return 0

    async with async_session_factory() as session:
        stmt = select(Shipment.id, Shipment.pod, Shipment.eta_current).where(
            Shipment.status == "on_sea"
        )
        rows = (await session.execute(stmt)).all()

    updated = 0
    for shipment_id, pod, eta_current in rows:
        located = geocode_port(pod) if pod else None
        if located is None:
            logger.info("tide poll: shipment %d POD %r không geocode được", shipment_id, pod)
            continue
        lat, lon, _locode = located

        if not _try_consume_quota():
            logger.warning(
                "tide poll: đạt quota %d call/ngày UTC — bỏ qua các lô còn lại",
                _MAX_DAILY_CALLS,
            )
            break

        try:
            tide = await fetch_tide(lat, lon, settings.STORMGLASS_API_KEY)
        except ExternalIntegrationError as exc:
            logger.warning("tide poll: shipment %d fetch failed: %s", shipment_id, exc)
            continue

        async with async_session_factory() as session:
            env = await session.get(EnvConditions, shipment_id)
            if env is None:
                env = EnvConditions(shipment_id=shipment_id)
                session.add(env)
            env.tide_extremes = tide.extremes
            env.tide_station_name = tide.station_name
            env.tide_station_distance_km = tide.station_distance_km
            env.tide_fetched_at = tide.fetched_at
            await session.commit()
        updated += 1

        if eta_current is not None and eta_current.tzinfo is None:
            eta_current = eta_current.replace(tzinfo=UTC)
        inside = eta_in_tidal_window(eta_current, tide.extremes, settings.TIDAL_WINDOW_HOURS)
        if inside is False:
            window = nearest_high_tide(eta_current, tide.extremes)
            await broadcast_tidal_alert(
                shipment_id,
                {
                    "eta_current": eta_current.isoformat(),
                    "nearest_window": window.isoformat() if window else None,
                    "message": "có thể phải chờ con nước",
                },
            )

    return updated


async def run() -> None:
    """Loop: poll, then sleep TIDE_POLL_HOURS, until cancelled."""
    interval_s = settings.TIDE_POLL_HOURS * 3600
    while True:
        try:
            updated = await _poll_once()
            if updated:
                logger.info("tide poll: updated %d shipment(s)", updated)
        except Exception:  # noqa: BLE001 — background job must survive one bad cycle
            logger.exception("tide poll cycle failed")
        await asyncio.sleep(interval_s)
