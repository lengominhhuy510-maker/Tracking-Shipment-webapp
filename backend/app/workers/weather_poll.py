"""Weather/current poll worker (Spec §6.2) — Open-Meteo, every WEATHER_POLL_HOURS.

For each on-sea shipment with a known position: fetch marine + wind conditions
and upsert the weather-owned fields of ``env_conditions``. Provider failures
keep the cached values (no write) and never crash the app.
"""

import asyncio
import logging

from sqlalchemy import select

from app.config import settings
from app.db.base import async_session_factory
from app.db.models import EnvConditions, Shipment
from app.integrations.errors import ExternalIntegrationError
from app.integrations.open_meteo import fetch_conditions

logger = logging.getLogger(__name__)


async def _poll_once() -> int:
    """Fetch + upsert weather for eligible shipments; return update count."""
    async with async_session_factory() as session:
        stmt = (
            select(Shipment.id, Shipment.current_lat, Shipment.current_lon)
            .where(Shipment.status == "on_sea")
            .where(Shipment.current_lat.is_not(None))
            .where(Shipment.current_lon.is_not(None))
        )
        rows = (await session.execute(stmt)).all()

    updated = 0
    for shipment_id, lat, lon in rows:
        try:
            conditions = await fetch_conditions(lat, lon)
        except ExternalIntegrationError as exc:
            logger.warning("weather poll: shipment %d fetch failed: %s", shipment_id, exc)
            continue

        async with async_session_factory() as session:
            env = await session.get(EnvConditions, shipment_id)
            if env is None:
                env = EnvConditions(shipment_id=shipment_id)
                session.add(env)
            env.wind_speed_kn = conditions.wind_speed_kn
            env.wave_height_m = conditions.wave_height_m
            env.current_speed_kn = conditions.current_speed_kn
            env.current_direction_deg = conditions.current_direction_deg
            env.weather_fetched_at = conditions.fetched_at
            await session.commit()
        updated += 1

    return updated


async def run() -> None:
    """Loop: poll, then sleep WEATHER_POLL_HOURS, until cancelled."""
    interval_s = settings.WEATHER_POLL_HOURS * 3600
    while True:
        try:
            updated = await _poll_once()
            if updated:
                logger.info("weather poll: updated %d shipment(s)", updated)
        except Exception:  # noqa: BLE001 — background job must survive one bad cycle
            logger.exception("weather poll cycle failed")
        await asyncio.sleep(interval_s)
