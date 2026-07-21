"""Offline model tests — SQLite async in-memory, no real DB required."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import enums
from app.db.base import Base
from app.db.models import Shipment  # noqa: F401 — registers all models on Base

EXPECTED_TABLES = {
    "shipments",
    "eta_history",
    "vessel_trail",
    "agent_proposals",
    "research_findings",
    "vessel_registry",
    "users",
    "shipment_legs",
    "env_conditions",
    "processed_emails",
}


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def test_metadata_has_all_10_tables():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_enum_values_no_diacritics():
    for values in (enums.RESEARCH_LEVEL, enums.ONBOARDING_STATUS, enums.EMAIL_OUTCOME):
        for v in values:
            assert v.isascii(), f"enum value {v!r} must be ASCII (IC§1.1)"
    assert "trung_binh" in enums.RESEARCH_LEVEL
    assert "thap" in enums.RESEARCH_LEVEL


def _make_shipment(**overrides) -> Shipment:
    defaults = dict(
        bl_number="BL-TEST-1",
        container_no="CSQU3054383",
        incoterm="FOB",
        shipment_direction="import",
        monitoring_mode="auto_email",
        carrier="Maersk",
        vessel_name="TEST VESSEL",
        pol="SGSIN",
        pod="VNCLI",
    )
    defaults.update(overrides)
    return Shipment(**defaults)


async def test_insert_and_query_shipment(session):
    session.add(_make_shipment())
    await session.commit()

    row = (await session.execute(select(Shipment))).scalar_one()
    assert row.bl_number == "BL-TEST-1"
    assert row.status == "new"
    assert row.shipment_type == "direct"
    assert row.onboarding_status == "pending"


async def test_check_constraint_rejects_bad_enum(session):
    session.add(_make_shipment(bl_number="BL-BAD", status="teleported"))
    with pytest.raises(Exception) as excinfo:
        await session.commit()
    assert "constraint" in str(excinfo.value).lower() or "CHECK" in str(excinfo.value)
