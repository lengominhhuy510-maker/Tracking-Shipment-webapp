"""TASK-13 — proposal approve/reject/409 + rollover chain §6.8d."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.db.models import EtaHistory, Shipment, ShipmentLeg
from app.services import proposal_service
from app.services.email_service import process_raw_email
from app.services.leg_service import resolve_and_activate_leg
from app.services.scrape_client import IMOResolverResult, ScrapeError
from tests.email_helpers import (
    fake_extract,
    make_extraction,
    make_raw_email,
    seed_shipment,
)


async def make_proposal(db, extraction, message_id="<p-1@maersk.com>") -> int:
    result = await process_raw_email(
        make_raw_email(message_id=message_id),
        session_factory=db,
        extract=fake_extract(extraction),
        broadcast=AsyncMock(),
    )
    assert result.proposal_ids
    return result.proposal_ids[0]


# --- approve: ETA update ---


async def test_approve_applies_eta_and_history(db):
    shipment_id, _ = await seed_shipment(db)
    proposal_id = await make_proposal(db, make_extraction())
    async with db() as session:
        proposal, rollover = await proposal_service.approve(session, proposal_id, user_id=7)
    assert proposal.status == "approved"
    assert proposal.decided_by == 7
    assert proposal.decided_at is not None
    assert rollover is None  # không có new_vessel_name → không rollover
    async with db() as session:
        shipment = await session.get(Shipment, shipment_id)
        assert shipment.eta_current is not None
        history = (
            await session.execute(
                select(EtaHistory).where(EtaHistory.shipment_id == shipment_id)
            )
        ).scalars().all()
        assert len(history) == 1
        assert history[0].source == "email_agent"
        assert f"#{proposal_id}" in history[0].note


# --- approve/reject đã quyết định → AlreadyDecided (API map 409) ---


async def test_approve_twice_raises_already_decided(db):
    await seed_shipment(db)
    proposal_id = await make_proposal(db, make_extraction())
    async with db() as session:
        await proposal_service.approve(session, proposal_id, user_id=1)
    async with db() as session:
        with pytest.raises(proposal_service.ProposalAlreadyDecided):
            await proposal_service.approve(session, proposal_id, user_id=2)


async def test_reject_then_approve_raises_already_decided(db):
    await seed_shipment(db)
    proposal_id = await make_proposal(db, make_extraction())
    async with db() as session:
        proposal = await proposal_service.reject(session, proposal_id, user_id=1, reason="sai")
    assert proposal.status == "rejected"
    assert proposal.decided_by == 1
    async with db() as session:
        with pytest.raises(proposal_service.ProposalAlreadyDecided):
            await proposal_service.approve(session, proposal_id, user_id=2)


async def test_approve_missing_proposal_raises_not_found(db):
    async with db() as session:
        with pytest.raises(proposal_service.ProposalNotFound):
            await proposal_service.approve(session, 999, user_id=1)


async def test_rejected_proposal_changes_nothing(db):
    shipment_id, _ = await seed_shipment(db)
    proposal_id = await make_proposal(db, make_extraction())
    async with db() as session:
        await proposal_service.reject(session, proposal_id, user_id=1)
    async with db() as session:
        shipment = await session.get(Shipment, shipment_id)
        assert shipment.eta_current is None
        history = (
            await session.execute(
                select(EtaHistory).where(EtaHistory.shipment_id == shipment_id)
            )
        ).scalars().all()
        assert history == []


# --- rollover §6.8d: leg mới SAME leg_no, superseded_at, activate sau scrape ---


def rollover_extraction():
    return make_extraction(
        to_voyage="V.002N", new_vessel_name="EVER ACE", email_type="rollover"
    )


async def test_approve_rollover_inserts_new_leg_same_leg_no(db):
    shipment_id, old_leg_id = await seed_shipment(db)
    proposal_id = await make_proposal(db, rollover_extraction())
    async with db() as session:
        _, rollover = await proposal_service.approve(session, proposal_id, user_id=1)
    assert rollover is not None
    assert rollover.vessel_name == "EVER ACE"
    assert rollover.voyage_no == "V.002N"

    async with db() as session:
        old_leg = await session.get(ShipmentLeg, old_leg_id)
        new_leg = await session.get(ShipmentLeg, rollover.new_leg_id)
        assert old_leg.superseded_at is not None
        assert new_leg.leg_no == old_leg.leg_no  # SAME leg_no — rollover ≠ transshipment
        assert new_leg.vessel_name == "EVER ACE"
        assert new_leg.voyage_no == "V.002N"
        assert new_leg.onboarding_status == "pending"  # IC§3.2: chờ resolver
        assert new_leg.is_active_leg is False  # chưa flip — chờ run_rollover
        assert old_leg.is_active_leg is True


async def test_run_rollover_success_activates_new_leg(db):
    shipment_id, old_leg_id = await seed_shipment(db)
    proposal_id = await make_proposal(db, rollover_extraction())
    async with db() as session:
        _, rollover = await proposal_service.approve(session, proposal_id, user_id=1)

    async def fake_resolve_imo(vessel, voyage, pol, pod):
        return IMOResolverResult(
            imo="9811000",
            mmsi="563012345",
            vessel_name="EVER ACE",
            confidence="cao",
            source_url="https://example.com/vessel/9811000",
        )

    signal = AsyncMock()
    broadcast = AsyncMock()

    async def activate(session, new_leg_id, imo, mmsi, resolved_via):
        await resolve_and_activate_leg(
            session, new_leg_id, imo, mmsi, resolved_via,
            resubscribe_signal=signal, broadcast=broadcast,
        )

    async with db() as session:
        await proposal_service.run_rollover(
            rollover, session, resolve_imo=fake_resolve_imo, activate=activate
        )

    async with db() as session:
        new_leg = await session.get(ShipmentLeg, rollover.new_leg_id)
        old_leg = await session.get(ShipmentLeg, old_leg_id)
        shipment = await session.get(Shipment, shipment_id)
        assert new_leg.is_active_leg is True
        assert new_leg.onboarding_status == "resolved"
        assert new_leg.imo == "9811000"
        assert new_leg.imo_resolved_via == "deterministic_scrape"
        assert old_leg.is_active_leg is False  # đúng 1 active leg
        active = (
            await session.execute(
                select(ShipmentLeg)
                .where(ShipmentLeg.shipment_id == shipment_id)
                .where(ShipmentLeg.is_active_leg)
            )
        ).scalars().all()
        assert len(active) == 1
        # mirror sang shipments
        assert shipment.imo == "9811000"
        assert shipment.mmsi == "563012345"
        assert shipment.onboarding_status == "resolved"
    signal.set.assert_called_once()
    broadcast.assert_awaited_once()


async def test_run_rollover_scrape_failure_marks_manual(db):
    shipment_id, old_leg_id = await seed_shipment(db)
    proposal_id = await make_proposal(db, rollover_extraction())
    async with db() as session:
        _, rollover = await proposal_service.approve(session, proposal_id, user_id=1)

    async def failing_resolve_imo(vessel, voyage, pol, pod):
        return ScrapeError("not_found")

    mark_manual = AsyncMock()
    activate = AsyncMock()
    async with db() as session:
        await proposal_service.run_rollover(
            rollover,
            session,
            resolve_imo=failing_resolve_imo,
            activate=activate,
            mark_manual=mark_manual,
        )
    activate.assert_not_awaited()
    mark_manual.assert_awaited_once()
    args = mark_manual.await_args.args
    assert args[1] == rollover.new_leg_id
    assert args[2] == "not_found"
