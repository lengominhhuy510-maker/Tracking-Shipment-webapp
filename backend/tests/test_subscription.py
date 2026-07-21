"""TDD tests for app.services.subscription (IC§2.3 query + resubscribe signal)."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Shipment
from app.services.subscription import ResubscribeSignal, desired_mmsi_set


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def _shipment(bl: str, mmsi: str | None, status: str, onboarding_status: str) -> Shipment:
    return Shipment(
        bl_number=bl,
        container_no="CSQU3054383",
        incoterm="FOB",
        shipment_direction="import",
        monitoring_mode="auto_email",
        carrier="Maersk",
        vessel_name="TEST VESSEL",
        pol="SGSIN",
        pod="VNCLI",
        mmsi=mmsi,
        status=status,
        onboarding_status=onboarding_status,
    )


async def test_desired_mmsi_set_filters_by_status(session):
    session.add_all(
        [
            _shipment("BL-1", "570000001", "on_sea", "resolved"),
            _shipment("BL-2", "570000002", "new", "resolved"),
            _shipment("BL-3", "570000003", "arrived", "resolved"),
            _shipment("BL-4", "570000004", "delivered", "resolved"),
            _shipment("BL-5", "570000005", "on_sea", "pending"),
            _shipment("BL-6", None, "on_sea", "resolved"),
        ]
    )
    await session.commit()

    result = await desired_mmsi_set(session)

    assert result == {"570000001", "570000002"}


async def test_desired_mmsi_set_empty_db(session):
    assert await desired_mmsi_set(session) == set()


async def test_desired_mmsi_set_dedupes_shared_mmsi(session):
    session.add_all(
        [
            _shipment("BL-A", "570000001", "on_sea", "resolved"),
            _shipment("BL-B", "570000001", "on_sea", "resolved"),
        ]
    )
    await session.commit()

    assert await desired_mmsi_set(session) == {"570000001"}


async def test_resubscribe_signal_set_wait_clear():
    sig = ResubscribeSignal()
    assert not sig.is_set()
    sig.set()
    assert sig.is_set()
    await sig.wait()
    sig.clear()
    assert not sig.is_set()
