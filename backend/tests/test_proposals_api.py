"""API-level regression for BUG: approve/reject proposal → 500 'transaction already begun'.

Root cause: the route depends on BOTH ``get_session`` and ``get_current_user``.
FastAPI caches ``Depends(get_session)`` per request, so ``get_current_user`` and
the handler share ONE session. ``get_current_user`` runs ``select(User)`` on it →
SQLAlchemy autobegin opens a transaction. The router then called
``proposal_service.approve`` / ``reject`` which did ``async with session.begin()``
on that already-begun session → ``InvalidRequestError`` → 500.

These tests use the REAL auth path (seeded User + genuine session cookie) rather
than ``auth_override`` — the override skips the ``select(User)`` query and would
NOT autobegin the session, so it would fail to reproduce the bug.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_session
from app.auth.jwt import issue_token
from app.db.base import Base
from app.db.models import AgentProposal, EtaHistory, Shipment, ShipmentLeg, User
from app.main import app


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            session.add(
                User(
                    id=1,
                    email="approver@example.com",
                    provider="google",
                    provider_sub="approver-sub",
                    role="user",
                )
            )
    yield factory
    await engine.dispose()


@pytest.fixture
async def client(db):
    """Real auth: NO get_current_user override, so its select(User) autobegins the
    shared request session — exactly the condition that triggered the bug."""

    async def override_session():
        async with db() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    cookies = {"session_token": issue_token(1, "user")}
    async with AsyncClient(
        transport=transport, base_url="http://test", cookies=cookies
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def _seed_pending_proposal(db, *, new_eta="2026-08-10T14:00:00+00:00") -> tuple[int, int]:
    """Insert one shipment + active leg + pending proposal; return (proposal_id, shipment_id)."""
    async with db() as session:
        async with session.begin():
            shipment = Shipment(
                bl_number="BL-PROP-1",
                container_no="MSKU1234565",
                incoterm="FOB",
                shipment_direction="import",
                carrier="Maersk",
                vessel_name="EVER GIVEN",
                voyage_no="V.001N",
                pol="SGSIN",
                pod="VNCLI",
                monitoring_mode="auto_email",
            )
            session.add(shipment)
            await session.flush()
            session.add(
                ShipmentLeg(
                    shipment_id=shipment.id,
                    leg_no=1,
                    vessel_name="EVER GIVEN",
                    voyage_no="V.001N",
                    pol="SGSIN",
                    pod="VNCLI",
                    is_active_leg=True,
                )
            )
            proposal = AgentProposal(
                shipment_id=shipment.id,
                source_email_id="<p-1@maersk.com>",
                extracted_json={
                    "containers": ["MSKU1234565"],
                    "from_voyage": "V.001N",
                    "to_voyage": None,
                    "new_eta": new_eta,
                    "new_vessel_name": None,
                    "reason": "delay",
                    "email_type": "transit_delay",
                },
                proposed_action="update_eta",
                status="pending",
            )
            session.add(proposal)
            await session.flush()
            return proposal.id, shipment.id


async def test_approve_pending_proposal_200(client, db):
    """Reproduces the bug: before the fix this returned 500 (transaction already begun)."""
    proposal_id, shipment_id = await _seed_pending_proposal(db)

    r = await client.post(f"/api/v1/agent-proposals/{proposal_id}/approve")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["decided_by"] == 1
    assert body["decided_at"] is not None

    async with db() as session:
        proposal = await session.get(AgentProposal, proposal_id)
        assert proposal.status == "approved"
        shipment = await session.get(Shipment, shipment_id)
        assert shipment.eta_current is not None
        history = (
            await session.execute(
                select(EtaHistory).where(EtaHistory.shipment_id == shipment_id)
            )
        ).scalars().all()
        assert len(history) == 1
        assert history[0].source == "email_agent"


async def test_reject_pending_proposal_200(client, db):
    proposal_id, shipment_id = await _seed_pending_proposal(db)

    r = await client.post(
        f"/api/v1/agent-proposals/{proposal_id}/reject", json={"reason": "sai"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "rejected"
    assert body["decided_by"] == 1

    async with db() as session:
        proposal = await session.get(AgentProposal, proposal_id)
        assert proposal.status == "rejected"
        # reject must not touch shipment ETA
        shipment = await session.get(Shipment, shipment_id)
        assert shipment.eta_current is None


async def test_approve_twice_returns_409(client, db):
    proposal_id, _ = await _seed_pending_proposal(db)

    r = await client.post(f"/api/v1/agent-proposals/{proposal_id}/approve")
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/v1/agent-proposals/{proposal_id}/approve")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "PROPOSAL_ALREADY_DECIDED"


async def test_approve_missing_returns_404(client):
    r = await client.post("/api/v1/agent-proposals/9999/approve")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "PROPOSAL_NOT_FOUND"
