from collections.abc import Awaitable, Callable

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Shipment, ShipmentLeg
from app.services.broadcast import broadcast_onboarding_update
from app.services.subscription import ResubscribeSignal

OnboardingBroadcast = Callable[[int, dict], Awaitable[None]]

resubscribe_signal = ResubscribeSignal()


async def resolve_leg(
    session: AsyncSession,
    leg_id: int,
    imo: str,
    mmsi: str | None,
    resolved_via: str,
    *,
    resubscribe_signal: ResubscribeSignal = resubscribe_signal,
    broadcast: OnboardingBroadcast = broadcast_onboarding_update,
) -> None:
    async with session.begin():
        leg = await session.get(ShipmentLeg, leg_id)
        if leg is None:
            raise ValueError(f"shipment leg {leg_id} not found")

        leg.imo = imo
        leg.mmsi = mmsi
        leg.onboarding_status = "resolved"
        leg.imo_resolved_via = resolved_via
        leg.onboarding_error = None

        if leg.is_active_leg:
            shipment = await session.get(Shipment, leg.shipment_id)
            if shipment is None:
                raise RuntimeError("active leg shipment missing")
            shipment.imo = imo
            shipment.mmsi = mmsi
            shipment.onboarding_status = "resolved"
            shipment.imo_resolved_via = resolved_via
            shipment.onboarding_error = None

        shipment_id = leg.shipment_id

    resubscribe_signal.set()
    await broadcast(
        shipment_id,
        {"onboarding_status": "resolved", "onboarding_error": None, "leg_id": leg_id},
    )


async def resolve_and_activate_leg(
    session: AsyncSession,
    new_leg_id: int,
    imo: str,
    mmsi: str | None,
    resolved_via: str,
    *,
    resubscribe_signal: ResubscribeSignal = resubscribe_signal,
    broadcast: OnboardingBroadcast = broadcast_onboarding_update,
) -> None:
    """Rollover §6.8d: resolve the new leg + switch active NOW, one transaction.

    Unlike transit's dual-signal gate (6.8c), rollover is human-approved so the
    active flag flips immediately; the old leg is demoted first so the partial
    unique index ``uq_legs_one_active`` never sees two active legs.
    """
    async with session.begin():
        leg = await session.get(ShipmentLeg, new_leg_id)
        if leg is None:
            raise ValueError(f"shipment leg {new_leg_id} not found")

        leg.imo = imo
        leg.mmsi = mmsi
        leg.onboarding_status = "resolved"
        leg.imo_resolved_via = resolved_via
        leg.onboarding_error = None

        await session.execute(
            update(ShipmentLeg)
            .where(ShipmentLeg.shipment_id == leg.shipment_id)
            .where(ShipmentLeg.is_active_leg)
            .where(ShipmentLeg.id != new_leg_id)
            .values(is_active_leg=False)
        )
        leg.is_active_leg = True

        shipment = await session.get(Shipment, leg.shipment_id)
        if shipment is None:
            raise RuntimeError("rollover leg shipment missing")
        shipment.imo = imo
        shipment.mmsi = mmsi
        shipment.onboarding_status = "resolved"
        shipment.imo_resolved_via = resolved_via
        shipment.onboarding_error = None

        shipment_id = leg.shipment_id

    resubscribe_signal.set()
    await broadcast(
        shipment_id,
        {"onboarding_status": "resolved", "onboarding_error": None, "leg_id": new_leg_id},
    )


async def mark_leg_manual(
    session: AsyncSession,
    leg_id: int,
    error_code: str,
    *,
    resubscribe_signal: ResubscribeSignal = resubscribe_signal,
    broadcast: OnboardingBroadcast = broadcast_onboarding_update,
) -> None:
    async with session.begin():
        leg = await session.get(ShipmentLeg, leg_id)
        if leg is None:
            raise ValueError(f"shipment leg {leg_id} not found")

        leg.onboarding_status = "manual_required"
        leg.onboarding_error = error_code

        if leg.is_active_leg:
            shipment = await session.get(Shipment, leg.shipment_id)
            if shipment is None:
                raise RuntimeError("active leg shipment missing")
            shipment.onboarding_status = "manual_required"
            shipment.onboarding_error = error_code

        shipment_id = leg.shipment_id

    resubscribe_signal.set()
    await broadcast(
        shipment_id,
        {
            "onboarding_status": "manual_required",
            "onboarding_error": error_code,
            "leg_id": leg_id,
        },
    )
