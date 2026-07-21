"""Shared helpers for email agent tests: in-memory DB, fixture mails, fake extract."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.email_agent import EmailExtraction
from app.db.base import Base
from app.db.models import Shipment, ShipmentLeg
from app.integrations.imap_client import RawEmail, parse_rfc822

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "emails"

CARRIER_DOMAINS = ["maersk.com", "msc.com", "one-line.com", "wanhai.com", "evergreen-line.com"]
FORWARDER_EMAILS = ["ops@uandi.example.com"]


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def load_fixture(name: str, uid: int = 1) -> RawEmail:
    raw_bytes = (FIXTURES_DIR / name).read_bytes()
    return parse_rfc822(raw_bytes, uid)


def make_raw_email(
    *,
    uid: int = 1,
    message_id: str = "<test-1@maersk.com>",
    from_address: str = "noreply@maersk.com",
    subject: str = "Test",
    body_text: str = "body",
) -> RawEmail:
    return RawEmail(
        uid=uid,
        message_id=message_id,
        from_address=from_address,
        subject=subject,
        body_text=body_text,
        folder="INBOX",
    )


def make_extraction(**overrides) -> EmailExtraction:
    data = {
        "containers": ["MSKU1234565"],
        "from_voyage": "V.001N",
        "to_voyage": None,
        "new_eta": "2026-08-10T14:00:00+00:00",
        "new_vessel_name": None,
        "reason": "delay",
        "email_type": "transit_delay",
    }
    data.update(overrides)
    return EmailExtraction.model_validate(data)


def fake_extract(extraction: EmailExtraction):
    async def _extract(subject: str, body: str) -> EmailExtraction:
        return extraction

    return _extract


async def seed_shipment(
    db,
    *,
    container_no: str = "MSKU1234565",
    bl_number: str = "BL-DEMO-001",
    vessel_name: str = "EVER GIVEN",
    voyage_no: str = "V.001N",
    with_leg: bool = True,
) -> tuple[int, int | None]:
    async with db() as session:
        shipment = Shipment(
            bl_number=bl_number,
            container_no=container_no,
            incoterm="FOB",
            shipment_direction="import",
            carrier="Maersk",
            vessel_name=vessel_name,
            voyage_no=voyage_no,
            pol="SGSIN",
            pod="VNCLI",
            monitoring_mode="auto_email",
        )
        session.add(shipment)
        await session.flush()
        leg_id = None
        if with_leg:
            leg = ShipmentLeg(
                shipment_id=shipment.id,
                leg_no=1,
                vessel_name=vessel_name,
                voyage_no=voyage_no,
                pol="SGSIN",
                pod="VNCLI",
                is_active_leg=True,
            )
            session.add(leg)
            await session.flush()
            leg_id = leg.id
        await session.commit()
        return shipment.id, leg_id
