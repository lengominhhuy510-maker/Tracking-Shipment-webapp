"""TASK-13 — allowlist kép (A/B), matching, container lạ, fixture smoke (§7.4, IC§14)."""

from unittest.mock import AsyncMock

import pytest

from app.agents.email_agent import EmailParseError
from app.db.models import AgentProposal, ProcessedEmail
from app.services.email_service import is_allowlisted, process_raw_email
from tests.email_helpers import (
    CARRIER_DOMAINS,
    FORWARDER_EMAILS,
    fake_extract,
    load_fixture,
    make_extraction,
    make_raw_email,
    seed_shipment,
)


# --- Allowlist kép (A) domain hãng suffix-match + (B) forwarder nội bộ ---


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("noreply@maersk.com", True),  # (A) exact domain
        ("alert@notification.maersk.com", True),  # (A) subdomain suffix-match
        ("x@msc.com", True),
        ("x@one-line.com", True),
        ("x@evilmaersk.com", False),  # suffix-match KHÔNG phải substring
        ("x@maersk.com.attacker.io", False),
        ("ops@uandi.example.com", True),  # (B) internal forwarder
        ("other@uandi.example.com", False),  # not in (B)
        ("x@gmail.com", False),
        ("not-an-email", False),
    ],
)
def test_dual_allowlist_suffix_match(address, expected):
    assert (
        is_allowlisted(
            address,
            carrier_domains=CARRIER_DOMAINS,
            forwarder_emails=FORWARDER_EMAILS,
        )
        is expected
    )


async def test_rejected_allowlist_outcome_recorded_no_llm_call(db):
    extract = AsyncMock()
    raw = make_raw_email(
        message_id="<spam-1@gmail.com>", from_address="attacker@gmail.com"
    )
    result = await process_raw_email(
        raw, session_factory=db, extract=extract, broadcast=AsyncMock()
    )
    assert result.outcome == "rejected_allowlist"
    extract.assert_not_awaited()
    async with db() as session:
        row = await session.get(ProcessedEmail, "<spam-1@gmail.com>")
        assert row.outcome == "rejected_allowlist"


# --- Matching + container lạ ---


async def test_matched_container_creates_one_proposal(db):
    shipment_id, _ = await seed_shipment(db)
    broadcast = AsyncMock()
    result = await process_raw_email(
        make_raw_email(),
        session_factory=db,
        extract=fake_extract(make_extraction()),
        broadcast=broadcast,
    )
    assert result.outcome == "proposals_created"
    assert len(result.proposal_ids) == 1
    async with db() as session:
        proposal = await session.get(AgentProposal, result.proposal_ids[0])
        assert proposal.shipment_id == shipment_id
        assert proposal.status == "pending"
        assert proposal.extracted_json["containers"] == ["MSKU1234565"]
    broadcast.assert_awaited_once()


async def test_multi_container_with_unknown_creates_partial_proposals(db):
    """Mail 3 IC§14: 2 container khớp + 1 lạ → 2 proposal, 1 unmatched, không chặn."""
    await seed_shipment(db, container_no="MSKU1234565", bl_number="BL-1")
    await seed_shipment(db, container_no="WHLU5500123", bl_number="BL-4")
    extraction = make_extraction(
        containers=["MSKU1234565", "ZZZU9999992", "WHLU5500123"]
    )
    result = await process_raw_email(
        make_raw_email(message_id="<multi-1@maersk.com>"),
        session_factory=db,
        extract=fake_extract(extraction),
        broadcast=AsyncMock(),
    )
    assert result.outcome == "proposals_created"
    assert len(result.proposal_ids) == 2
    async with db() as session:
        row = await session.get(ProcessedEmail, "<multi-1@maersk.com>")
        assert row.unmatched_containers == ["ZZZU9999992"]


async def test_invalid_checkdigit_container_is_unmatched_not_crash(db):
    await seed_shipment(db)
    extraction = make_extraction(containers=["MSKU1234565", "AAAA1111111"])
    result = await process_raw_email(
        make_raw_email(message_id="<badcd-1@maersk.com>"),
        session_factory=db,
        extract=fake_extract(extraction),
        broadcast=AsyncMock(),
    )
    assert result.outcome == "proposals_created"
    async with db() as session:
        row = await session.get(ProcessedEmail, "<badcd-1@maersk.com>")
        assert row.unmatched_containers == ["AAAA1111111"]


async def test_no_match_outcome_when_no_container_in_system(db):
    result = await process_raw_email(
        make_raw_email(message_id="<nomatch-1@maersk.com>"),
        session_factory=db,
        extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    assert result.outcome == "no_match"
    assert result.proposal_ids == ()


async def test_parse_failed_outcome_when_extract_fails(db):
    async def failing_extract(subject, body):
        raise EmailParseError("bad LLM output twice")

    result = await process_raw_email(
        make_raw_email(message_id="<parsefail-1@maersk.com>"),
        session_factory=db,
        extract=failing_extract,
        broadcast=AsyncMock(),
    )
    assert result.outcome == "parse_failed"
    async with db() as session:
        row = await session.get(ProcessedEmail, "<parsefail-1@maersk.com>")
        assert row.outcome == "parse_failed"


# --- 4 outcome cố định — không có giá trị thứ 5 ---


async def test_only_four_outcomes_exist(db):
    from app.db.enums import EMAIL_OUTCOME

    assert set(EMAIL_OUTCOME) == {
        "proposals_created",
        "no_match",
        "rejected_allowlist",
        "parse_failed",
    }


# --- Fixture smoke (IC§14, offline — fake extract mô phỏng LLM) ---


async def test_fixture_mail1_rollover_parses_and_matches(db):
    shipment_id, _ = await seed_shipment(db)
    raw = load_fixture("mail1_rollover.eml")
    assert raw.from_address == "noreply@notification.maersk.com"
    assert is_allowlisted(
        raw.from_address,
        carrier_domains=CARRIER_DOMAINS,
        forwarder_emails=FORWARDER_EMAILS,
    )
    extraction = make_extraction(
        to_voyage="V.002N", new_vessel_name="EVER ACE", email_type="rollover"
    )
    result = await process_raw_email(
        raw, session_factory=db, extract=fake_extract(extraction), broadcast=AsyncMock()
    )
    assert result.outcome == "proposals_created"
    async with db() as session:
        proposal = await session.get(AgentProposal, result.proposal_ids[0])
        assert proposal.proposed_action == "rollover"
        assert proposal.extracted_json["new_vessel_name"] == "EVER ACE"


async def test_fixture_mail4_forwarder_still_creates_proposal(db):
    """Mail 4 IC§14: forward tay từ (B) — vẫn đọc + proposal (mode không gate đọc)."""
    await seed_shipment(db, container_no="TEMU8123455", bl_number="BL-2")
    raw = load_fixture("mail4_forwarded.eml")
    assert raw.from_address == "ops@uandi.example.com"
    extraction = make_extraction(containers=["TEMU8123455"])
    result = await process_raw_email(
        raw,
        session_factory=db,
        extract=fake_extract(extraction),
        broadcast=AsyncMock(),
        carrier_domains=CARRIER_DOMAINS,
        forwarder_emails=FORWARDER_EMAILS,
    )
    assert result.outcome == "proposals_created"
    assert len(result.proposal_ids) == 1


async def test_fixture_mails_parse_rfc822_fields(db):
    mail2 = load_fixture("mail2_delay.eml")
    assert mail2.message_id == "<delay-002@one-line.com>"
    assert mail2.from_address == "notification@one-line.com"
    assert "ONEU4001233" in mail2.body_text
    mail3 = load_fixture("mail3_multi_container.eml")
    assert "ZZZU9999992" in mail3.body_text
