"""Vessel trail snapshot job (Spec §3.1b).

Every ``TRAIL_SNAPSHOT_HOURS`` hours, for each on-sea shipment with a known
position, append a ``vessel_trail`` point IF the most recent point is at least
``TRAIL_SNAPSHOT_HOURS`` old (or none exists). Keeps a rolling window of the 12
most recent points per shipment — older ones are deleted.

Runs embedded in the FastAPI process via lifespan; cancelled cleanly on shutdown.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from app.config import settings
from app.db.base import async_session_factory
from app.db.models import Shipment, VesselTrail

logger = logging.getLogger(__name__)

_MAX_TRAIL_POINTS = 12


async def _snapshot_once() -> int:
    """Append trail points for eligible shipments; return how many were added."""
    threshold = timedelta(hours=settings.TRAIL_SNAPSHOT_HOURS)
    now = datetime.now(UTC)
    added = 0

    async with async_session_factory() as session:
        stmt = (
            select(Shipment.id, Shipment.current_lat, Shipment.current_lon, Shipment.current_sog)
            .where(Shipment.status == "on_sea")
            .where(Shipment.current_lat.is_not(None))
            .where(Shipment.current_lon.is_not(None))
        )
        rows = (await session.execute(stmt)).all()

        for shipment_id, lat, lon, sog in rows:
            last_at = (
                await session.execute(
                    select(func.max(VesselTrail.recorded_at)).where(
                        VesselTrail.shipment_id == shipment_id
                    )
                )
            ).scalar_one_or_none()

            if last_at is not None:
                if last_at.tzinfo is None:
                    last_at = last_at.replace(tzinfo=UTC)
                if now - last_at < threshold:
                    continue

            session.add(VesselTrail(shipment_id=shipment_id, lat=lat, lon=lon, sog=sog))
            added += 1

        await session.commit()
        await _trim_trails(session)
        await session.commit()

    return added


async def _trim_trails(session) -> None:
    """Delete all but the 12 most recent points per shipment."""
    shipment_ids = (
        (await session.execute(select(VesselTrail.shipment_id).distinct())).scalars().all()
    )

    for shipment_id in shipment_ids:
        keep = (
            (
                await session.execute(
                    select(VesselTrail.id)
                    .where(VesselTrail.shipment_id == shipment_id)
                    .order_by(VesselTrail.recorded_at.desc(), VesselTrail.id.desc())
                    .limit(_MAX_TRAIL_POINTS)
                )
            )
            .scalars()
            .all()
        )
        if len(keep) < _MAX_TRAIL_POINTS:
            continue
        await session.execute(
            delete(VesselTrail)
            .where(VesselTrail.shipment_id == shipment_id)
            .where(VesselTrail.id.not_in(keep))
        )


async def run() -> None:
    """Loop: snapshot, then sleep TRAIL_SNAPSHOT_HOURS, until cancelled."""
    interval_s = settings.TRAIL_SNAPSHOT_HOURS * 3600
    while True:
        try:
            added = await _snapshot_once()
            if added:
                logger.info("trail snapshot: added %d point(s)", added)
        except Exception:  # noqa: BLE001 — background job must survive one bad cycle
            logger.exception("trail snapshot cycle failed")
        await asyncio.sleep(interval_s)
