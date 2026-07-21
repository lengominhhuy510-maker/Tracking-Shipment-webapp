"""Seed: 4 shipments + 2 users per IC§13. Idempotent (upsert) — safe to re-run.

Three goals, one script, switched by .env (IC§13 [v0.9.12]):
(a) offline-deterministic — no DEV_SEED_VESSEL_NAME: 4 static placeholder
    shipments, all resolved with placeholder IMO/MMSI (AIS_MODE=replay fixture);
(b) live-integration — DEV_SEED_VESSEL_NAME(+VOYAGE): shipment #1 uses the dev
    vessel; with IMO+MMSI too → resolved shortcut, without → pending (waits for
    IMO Resolver TASK-11);
(c) demo — fill real vessel values right before demo day.

Run: python -m app.db.seed
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import async_session_factory
from app.db.models import Shipment, ShipmentLeg, User

# Placeholder MMSIs match backend/tests/fixtures/ais_positions.json (replay mode)
PLACEHOLDER_VESSELS = {
    1: {"vessel_name": "DEMO VESSEL ALPHA", "voyage_no": "V.001N", "imo": "9000001", "mmsi": "570000001"},
    2: {"vessel_name": "DEMO VESSEL BRAVO", "voyage_no": "V.100E", "imo": "9000002", "mmsi": "570000002"},
    3: {"vessel_name": "DEMO VESSEL CHARLIE", "voyage_no": "V.200S", "imo": "9000003", "mmsi": "570000003"},
    # Lô 4: cùng vessel_name lô 1, khác voyage (IC§13 — duplicate-name test case)
    4: {"vessel_name": "DEMO VESSEL ALPHA", "voyage_no": "V.002S", "imo": "9000001", "mmsi": "570000001"},
}

NOW = datetime.now(timezone.utc)

# bl_number is the stable idempotency key for seed shipments
SHIPMENTS = [
    {
        "bl_number": "SEED-BL-0001",
        "container_no": "CSQU3054383",
        "incoterm": "FOB",
        "shipment_direction": "import",
        "monitoring_mode": "auto_email",
        "carrier": "Maersk",
        "pol": "SGSIN Singapore",
        "pod": "VNCLI Cat Lai",
        "eta_original": NOW + timedelta(days=5),
        "eta_original_source": "manual",
        "eta_current": NOW + timedelta(days=5),
        "atd": NOW - timedelta(days=2),
        "status": "on_sea",
    },
    {
        "bl_number": "SEED-BL-0002",
        "container_no": "MSKU9070323",
        "incoterm": "CIF",
        "shipment_direction": "import",
        "monitoring_mode": "manual",
        "carrier": "MSC",
        "pol": "HKHKG Hong Kong",
        "pod": "VNCLI Cat Lai",
        "eta_original": NOW + timedelta(days=6),
        "eta_original_source": "manual",
        "eta_current": NOW + timedelta(days=6),
        "atd": NOW - timedelta(days=1),
        "status": "on_sea",
    },
    {
        # BẮT BUỘC: lô 3 = export C/D VNCLI→SGSIN (export×CIF → auto_email)
        "bl_number": "SEED-BL-0003",
        "container_no": "TGHU7654320",
        "incoterm": "CIF",
        "shipment_direction": "export",
        "monitoring_mode": "auto_email",
        "carrier": "ONE",
        "pol": "VNCLI Cat Lai",
        "pod": "SGSIN Singapore",
        "eta_original": NOW + timedelta(days=4),
        "eta_original_source": "manual",
        "eta_current": NOW + timedelta(days=4),
        "atd": NOW - timedelta(days=1),
        "status": "on_sea",
    },
    {
        "bl_number": "SEED-BL-0004",
        "container_no": "CBHU8437299",
        "incoterm": "FOB",
        "shipment_direction": "import",
        "monitoring_mode": "auto_email",
        "carrier": "Wan Hai",
        "pol": "TWKHH Kaohsiung",
        "pod": "VNCLI Cat Lai",
        "eta_original": NOW + timedelta(days=7),
        "eta_original_source": "manual",
        "eta_current": NOW + timedelta(days=7),
        "atd": NOW - timedelta(days=3),
        "status": "on_sea",
    },
]

USERS = [
    {"email": "admin@demo", "name": "Demo Admin", "provider": "google",
     "provider_sub": "seed-admin-sub", "role": "admin"},
    {"email": "user@demo", "name": "Demo User", "provider": "google",
     "provider_sub": "seed-user-sub", "role": "user"},
]


def _vessel_identity(seq: int) -> dict:
    """Vessel identity + onboarding state for shipment #seq per IC§13 branches."""
    placeholder = PLACEHOLDER_VESSELS[seq]
    name = settings.DEV_SEED_VESSEL_NAME.strip()

    if not name:
        # Branch (d): no dev vessel — all 4 static placeholders, resolved
        return {
            **placeholder,
            "onboarding_status": "resolved",
            "imo_resolved_via": "manual",
        }

    if seq != 1:
        return {
            **placeholder,
            "onboarding_status": "resolved",
            "imo_resolved_via": "manual",
        }

    # Shipment #1 uses the dev vessel
    voyage = settings.DEV_SEED_VESSEL_VOYAGE.strip() or placeholder["voyage_no"]
    imo = settings.DEV_SEED_VESSEL_IMO.strip()
    mmsi = settings.DEV_SEED_VESSEL_MMSI.strip()
    if imo and mmsi:
        # Branch (b): live shortcut — resolved with real IMO/MMSI
        return {
            "vessel_name": name,
            "voyage_no": voyage,
            "imo": imo,
            "mmsi": mmsi,
            "onboarding_status": "resolved",
            "imo_resolved_via": "manual",
        }
    # Branch (c): NAME+VOYAGE only — pending, waits for IMO Resolver (TASK-11)
    return {
        "vessel_name": name,
        "voyage_no": voyage,
        "imo": None,
        "mmsi": None,
        "onboarding_status": "pending",
        "imo_resolved_via": None,
    }


async def _upsert_users(session: AsyncSession) -> None:
    for u in USERS:
        existing = (
            await session.execute(
                select(User).where(
                    User.provider == u["provider"], User.provider_sub == u["provider_sub"]
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(User(**u))
        else:
            existing.email = u["email"]
            existing.name = u["name"]
            existing.role = u["role"]


async def _upsert_shipment(session: AsyncSession, seq: int, data: dict) -> None:
    identity = _vessel_identity(seq)
    row = {
        **data,
        "vessel_name": identity["vessel_name"],
        "voyage_no": identity["voyage_no"],
        "imo": identity["imo"],
        "mmsi": identity["mmsi"],
        "imo_resolved_via": identity["imo_resolved_via"],
        "onboarding_status": identity["onboarding_status"],
        "shipment_type": "direct",
    }

    existing = (
        await session.execute(select(Shipment).where(Shipment.bl_number == data["bl_number"]))
    ).scalar_one_or_none()

    if existing is None:
        shipment = Shipment(**row)
        session.add(shipment)
        await session.flush()
    else:
        for key, value in row.items():
            setattr(existing, key, value)
        shipment = existing
        await session.flush()

    # 1 active leg per shipment (leg_no=1). Deactivate others first so the
    # partial unique index uq_legs_one_active never trips on re-run.
    leg = (
        await session.execute(
            select(ShipmentLeg).where(
                ShipmentLeg.shipment_id == shipment.id, ShipmentLeg.leg_no == 1
            )
        )
    ).scalar_one_or_none()

    leg_values = {
        "vessel_name": identity["vessel_name"],
        "voyage_no": identity["voyage_no"],
        "imo": identity["imo"],
        "mmsi": identity["mmsi"],
        "imo_resolved_via": identity["imo_resolved_via"],
        "onboarding_status": identity["onboarding_status"],
        "pol": data["pol"],
        "pod": data["pod"],
    }

    if leg is None:
        await session.execute(
            update(ShipmentLeg)
            .where(ShipmentLeg.shipment_id == shipment.id, ShipmentLeg.is_active_leg)
            .values(is_active_leg=False)
        )
        session.add(
            ShipmentLeg(shipment_id=shipment.id, leg_no=1, is_active_leg=True, **leg_values)
        )
    else:
        for key, value in leg_values.items():
            setattr(leg, key, value)
        leg.is_active_leg = True


async def seed(session: AsyncSession) -> None:
    await _upsert_users(session)
    for seq, data in enumerate(SHIPMENTS, start=1):
        await _upsert_shipment(session, seq, data)


async def main() -> None:
    async with async_session_factory() as session:
        async with session.begin():
            await seed(session)
    print("Seed OK: 4 shipments + 2 users (idempotent)")


if __name__ == "__main__":
    asyncio.run(main())
