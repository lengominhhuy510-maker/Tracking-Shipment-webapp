"""AIS worker orchestration (Spec §3.1 / §3.1b).

Selects a source by ``AIS_MODE`` (live WebSocket vs replay fixture), parses each
raw message, upserts ``shipments.current_*`` in place by MMSI, broadcasts the
position, and (once TASK-05 lands) recomputes ETA. Runs embedded in the FastAPI
process via lifespan; a resubscribe loop polls the desired MMSI set every
``AIS_RESUBSCRIBE_POLL_SECONDS`` with an asyncio.Event fast-path.

Forward-reference: ``recompute_eta`` (TASK-05) may not exist yet — the import is
guarded so the worker never crashes without it.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Protocol

from sqlalchemy import update

from app.config import settings
from app.db.base import async_session_factory
from app.db.models import Shipment
from app.services.broadcast import broadcast_position
from app.services.subscription import ResubscribeSignal, desired_mmsi_set
from app.workers.ais.parser import AisPosition, parse_ais_message
from app.workers.ais.replay_source import ReplaySource
from app.workers.ais.stream_client import StreamClient

logger = logging.getLogger(__name__)

try:
    from app.services.eta_service import recompute_eta
except ImportError:  # TASK-05 not implemented yet — skip ETA, never crash.
    recompute_eta = None


class AisSource(Protocol):
    """Structural interface shared by live (StreamClient) and replay (ReplaySource)."""

    def messages(self) -> AsyncIterator[dict]: ...

    async def resubscribe(self, mmsi_set: set[str]) -> None: ...

    async def aclose(self) -> None: ...


def _build_source(mmsi_set: set[str]) -> AisSource:
    if settings.AIS_MODE == "replay":
        return ReplaySource()
    return StreamClient(mmsi_set)


async def _apply_position(pos: AisPosition) -> None:
    """UPDATE-in-place shipments.current_* for every shipment with this MMSI."""
    async with async_session_factory() as session:
        result = await session.execute(
            update(Shipment)
            .where(Shipment.mmsi == pos.mmsi)
            .values(
                current_lat=pos.lat,
                current_lon=pos.lon,
                current_sog=pos.sog,
                current_cog=pos.cog,
                position_updated_at=pos.timestamp,
            )
            .returning(Shipment.id)
        )
        shipment_ids = [row[0] for row in result.all()]
        await session.commit()

    data = {
        "lat": pos.lat,
        "lon": pos.lon,
        "sog": pos.sog,
        "cog": pos.cog,
        "position_updated_at": pos.timestamp.isoformat(),
    }
    for shipment_id in shipment_ids:
        await broadcast_position(shipment_id, data)
        if recompute_eta is not None:
            async with async_session_factory() as session:
                await recompute_eta(session, shipment_id)


async def _resubscribe_loop(source: AisSource, signal: ResubscribeSignal) -> None:
    """Poll the desired MMSI set every N seconds, or immediately on signal."""
    while True:
        async with async_session_factory() as session:
            mmsi_set = await desired_mmsi_set(session)
        await source.resubscribe(mmsi_set)
        try:
            await asyncio.wait_for(signal.wait(), timeout=settings.AIS_RESUBSCRIBE_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass
        else:
            signal.clear()


async def run(signal: ResubscribeSignal | None = None) -> None:
    """Main entrypoint: consume the source and upsert positions until cancelled."""
    signal = signal or ResubscribeSignal()
    async with async_session_factory() as session:
        mmsi_set = await desired_mmsi_set(session)
    source = _build_source(mmsi_set)

    resubscribe_task = asyncio.create_task(_resubscribe_loop(source, signal))
    try:
        async for msg in source.messages():
            pos = parse_ais_message(msg)
            if pos is not None:
                await _apply_position(pos)
    finally:
        resubscribe_task.cancel()
        try:
            await resubscribe_task
        except asyncio.CancelledError:
            pass
        await source.aclose()
