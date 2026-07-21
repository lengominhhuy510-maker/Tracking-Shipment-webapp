"""MMSI subscription set (IC§2.3) + resubscribe signal for the AIS worker.

The worker swaps-and-replaces its full MMSI subscription (Spec §3.1); this module
computes that full set and provides an asyncio.Event wrapper so shipment changes
can trigger a fast-path resubscribe between the 60s polls.
"""

import asyncio

from sqlalchemy import select

from app.db.models import Shipment

_ACTIVE_EXCLUDED = ("arrived", "delivered")


async def desired_mmsi_set(session) -> set[str]:
    """MMSIs to subscribe: onboarding_status='resolved', status NOT arrived/delivered."""
    stmt = (
        select(Shipment.mmsi)
        .where(Shipment.onboarding_status == "resolved")
        .where(Shipment.status.not_in(_ACTIVE_EXCLUDED))
        .where(Shipment.mmsi.is_not(None))
    )
    rows = await session.execute(stmt)
    return {mmsi for (mmsi,) in rows if mmsi}


class ResubscribeSignal:
    """Thin wrapper over asyncio.Event for the worker's fast-path resubscribe."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def set(self) -> None:
        self._event.set()

    def clear(self) -> None:
        self._event.clear()

    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> bool:
        return await self._event.wait()
