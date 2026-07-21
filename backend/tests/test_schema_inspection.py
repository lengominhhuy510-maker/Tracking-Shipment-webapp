"""Schema inspection against a REAL Postgres (post `alembic upgrade head`).

Skipped when Postgres is unreachable (offline CI on SQLite). Set
TEST_DATABASE_URL to point at the migrated DB; falls back to
settings.DATABASE_URL.
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db.models import Shipment, ShipmentLeg

DB_URL = os.environ.get("TEST_DATABASE_URL", settings.DATABASE_URL)

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


def _postgres_available() -> bool:
    if not DB_URL.startswith("postgresql"):
        return False

    async def _ping() -> None:
        engine = create_async_engine(DB_URL)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    try:
        asyncio.run(asyncio.wait_for(_ping(), timeout=5))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(), reason="real Postgres not reachable — schema inspection skipped"
)


@pytest.fixture
async def engine():
    # NullPool + function scope: each test runs in its own event loop (pytest-asyncio),
    # so a pooled connection bound to a prior loop would break on reuse/close.
    eng = create_async_engine(DB_URL, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
        await s.rollback()


async def _inspect(engine, fn):
    async with engine.connect() as conn:
        return await conn.run_sync(lambda sync_conn: fn(inspect(sync_conn)))


async def test_all_10_tables_exist(engine):
    names = await _inspect(engine, lambda insp: insp.get_table_names())
    assert EXPECTED_TABLES <= set(names)


async def test_partial_unique_index_uq_legs_one_active(engine):
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_legs_one_active'")
            )
        ).fetchone()
    assert row is not None, "uq_legs_one_active missing — migration incomplete, do NOT mark [x]"
    indexdef = row[0]
    assert "UNIQUE" in indexdef
    assert "WHERE" in indexdef and "is_active_leg" in indexdef


async def test_required_indexes_exist(engine):
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
            )
        ).fetchall()
    names = {r[0] for r in rows}
    required = {
        "ix_shipments_status",
        "ix_shipments_onboarding",
        "ix_shipments_mmsi",
        "uq_legs_one_active",
        "ix_legs_shipment",
        "ix_trail_shipment_time",
        "ix_etahist_shipment_time",
        "ix_findings_route_time",
        "ix_proposals_status",
        "uq_proposals_email_shipment",
        "uq_users_provider_sub",
        "ix_registry_name",
    }
    assert required <= names, f"missing indexes: {required - names}"


async def test_check_constraint_rejects_bad_enum(session):
    session.add(
        Shipment(
            bl_number=f"BL-CHK-{uuid.uuid4().hex[:8]}",
            container_no="CSQU3054383",
            incoterm="FOB",
            shipment_direction="import",
            monitoring_mode="auto_email",
            carrier="Maersk",
            vessel_name="CHECK VESSEL",
            pol="SGSIN",
            pod="VNCLI",
            status="teleported",
        )
    )
    with pytest.raises((IntegrityError, DBAPIError)):
        await session.flush()


async def test_db_enforces_single_active_leg(session):
    shipment = Shipment(
        bl_number=f"BL-LEG-{uuid.uuid4().hex[:8]}",
        container_no="CSQU3054383",
        incoterm="FOB",
        shipment_direction="import",
        monitoring_mode="auto_email",
        carrier="Maersk",
        vessel_name="LEG VESSEL",
        pol="SGSIN",
        pod="VNCLI",
    )
    session.add(shipment)
    await session.flush()

    common = dict(
        shipment_id=shipment.id,
        vessel_name="LEG VESSEL",
        pol="SGSIN",
        pod="VNCLI",
        is_active_leg=True,
    )
    session.add(ShipmentLeg(leg_no=1, **common))
    await session.flush()
    session.add(ShipmentLeg(leg_no=2, **common))
    with pytest.raises((IntegrityError, DBAPIError)) as excinfo:
        await session.flush()
    assert "uq_legs_one_active" in str(excinfo.value)


async def test_fk_on_delete_rules(engine):
    def collect(insp):
        return {
            table: insp.get_foreign_keys(table)
            for table in (
                "eta_history",
                "vessel_trail",
                "agent_proposals",
                "research_findings",
                "shipment_legs",
                "env_conditions",
            )
        }

    fks = await _inspect(engine, collect)
    for table, table_fks in fks.items():
        for fk in table_fks:
            ondelete = (fk.get("options") or {}).get("ondelete", "").upper()
            if fk["referred_table"] == "shipments":
                assert ondelete == "CASCADE", f"{table} FK->shipments must be CASCADE"
            elif fk["referred_table"] == "users":
                assert ondelete == "RESTRICT", f"{table} FK->users must be RESTRICT"
