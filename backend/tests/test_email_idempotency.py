"""TASK-13 — idempotency: cùng mail 2 lần → proposal KHÔNG tăng (Patch p2 dedup)."""

from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app.db.models import AgentProposal, ProcessedEmail
from app.services.email_service import process_raw_email
from tests.email_helpers import (
    fake_extract,
    load_fixture,
    make_extraction,
    make_raw_email,
    seed_shipment,
)


async def _proposal_count(db) -> int:
    async with db() as session:
        return (await session.execute(select(func.count(AgentProposal.id)))).scalar_one()


async def test_same_mail_twice_does_not_increase_proposals(db):
    """Fixture smoke bắt buộc: cùng mail 2 lần → proposal count không tăng."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<dup-1@maersk.com>")
    extract = fake_extract(make_extraction())

    first = await process_raw_email(
        raw, session_factory=db, extract=extract, broadcast=AsyncMock()
    )
    assert first.outcome == "proposals_created"
    assert await _proposal_count(db) == 1

    second = await process_raw_email(
        raw, session_factory=db, extract=extract, broadcast=AsyncMock()
    )
    assert second.outcome is None  # dedup skip — không ghi gì thêm
    assert second.proposal_ids == ()
    assert await _proposal_count(db) == 1


async def test_dedup_skip_does_not_call_llm(db):
    await seed_shipment(db)
    raw = make_raw_email(message_id="<dup-llm@maersk.com>")
    await process_raw_email(
        raw, session_factory=db, extract=fake_extract(make_extraction()), broadcast=AsyncMock()
    )
    extract_spy = AsyncMock()
    await process_raw_email(
        raw, session_factory=db, extract=extract_spy, broadcast=AsyncMock()
    )
    extract_spy.assert_not_awaited()


async def test_one_mail_two_shipments_one_proposal_each(db):
    """Unique (source_email_id, shipment_id): mỗi shipment đúng 1 proposal/mail."""
    await seed_shipment(db, container_no="MSKU1234565", bl_number="BL-1")
    await seed_shipment(db, container_no="WHLU5500123", bl_number="BL-4")
    extraction = make_extraction(containers=["MSKU1234565", "WHLU5500123"])
    raw = make_raw_email(message_id="<pair-1@maersk.com>")

    await process_raw_email(
        raw, session_factory=db, extract=fake_extract(extraction), broadcast=AsyncMock()
    )
    await process_raw_email(
        raw, session_factory=db, extract=fake_extract(extraction), broadcast=AsyncMock()
    )
    assert await _proposal_count(db) == 2


async def test_fixture_mail_reprocessed_twice_count_stable(db):
    await seed_shipment(db)
    raw = load_fixture("mail1_rollover.eml")
    extraction = make_extraction(
        to_voyage="V.002N", new_vessel_name="EVER ACE", email_type="rollover"
    )
    for _ in range(2):
        await process_raw_email(
            raw, session_factory=db, extract=fake_extract(extraction), broadcast=AsyncMock()
        )
    assert await _proposal_count(db) == 1
    async with db() as session:
        rows = (await session.execute(select(func.count(ProcessedEmail.message_id)))).scalar_one()
        assert rows == 1
