"""QA-09 — Email idempotency 2 lớp + allowlist kép + thứ tự \\Seen (REPORT-ONLY).

Truth:
  Spec §7.1 (luồng: đọc mọi mail hợp lệ, map container, container lạ → log,
    proposal cho container khớp, KHÔNG sửa shipments),
  Spec §7.2 (human-in-the-loop, mail untrusted),
  Spec §7.4 (allowlist kép A/B trên From ngoài cùng; STORE \\Seen sau xử lý;
    2 lớp phòng vệ \\Seen + processed_emails),
  IC§0.2 / IC§2.2 bảng 10 (processed_emails: message_id PK, outcome, seen_set_at),
  IC§2.2 [v0.9.12] (2 lớp idempotency: dedup message_id chặn TRƯỚC extract;
    unique (source_email_id, shipment_id) chặn ghi-trùng nếu lọt — GIỮ 4 outcome,
    KHÔNG partial_match),
  IC§4.2 (EmailExtraction shape),
  IC§8 / §7.4 (allowlist A = suffix-match domain hãng; B = email forwarder đầy đủ),
  IC§14 (4 mail mẫu — mail 3 nhiều container + 1 lạ).

Mode: offline. KHÔNG IMAP thật, KHÔNG LLM thật.
  - Mail đọc từ fixtures/emails/*.eml qua parse_rfc822 (transport thật, offline).
  - LLM mock ở boundary ``extract`` với async signature đúng
    (``async def(subject, body) -> EmailExtraction``).
  - ``forward_service.auto_forward`` bị mock/patch trong MỌI đường proposals_created
    để KHÔNG mở SMTP thật (auto_email shipment kích hoạt outbound send — offline-safe).
  - Đường "suspect" (async-warning) chạy dưới ``-W error::RuntimeWarning`` để bắt
    coroutine chưa await.

Các cột SoT map → test function ghi ở đầu mỗi nhóm; xem qa_reports/QA-09.md.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.agents.email_agent import EmailParseError
from app.db.enums import EMAIL_OUTCOME
from app.db.models import AgentProposal, ProcessedEmail, Shipment
from app.integrations.errors import ExternalIntegrationError
from app.services import email_service
from app.services.email_service import (
    is_allowlisted,
    poll_once,
    process_raw_email,
)
from tests.email_helpers import (
    CARRIER_DOMAINS,
    FORWARDER_EMAILS,
    fake_extract,
    load_fixture,
    make_extraction,
    make_raw_email,
    seed_shipment,
)


# ---------------------------------------------------------------------------
# Offline guards + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_real_smtp():
    """HARD offline gate: never let auto_forward open SMTP.

    A ``proposals_created`` outcome on an ``auto_email`` shipment calls
    ``forward_service.auto_forward`` after commit. Patch it to an AsyncMock so
    the QA suite is fully offline and no outbound mail is attempted.
    """
    with patch.object(
        email_service.forward_service, "auto_forward", new=AsyncMock(return_value=False)
    ) as mock_fwd:
        yield mock_fwd


async def _proposal_count(db, message_id: str | None = None) -> int:
    async with db() as session:
        stmt = select(func.count(AgentProposal.id))
        if message_id is not None:
            stmt = stmt.where(AgentProposal.source_email_id == message_id)
        return (await session.execute(stmt)).scalar_one()


async def _processed_count(db) -> int:
    async with db() as session:
        return (
            await session.execute(select(func.count(ProcessedEmail.message_id)))
        ).scalar_one()


def make_imap(mails):
    imap = AsyncMock()
    imap.fetch_unseen.return_value = list(mails)
    return imap


# ===========================================================================
# GROUP 1 — Idempotency LAYER 1: application dedup on message_id
#   (blocks BEFORE extract; §7.4 2 lớp; IC§2.2 [v0.9.12])
# ===========================================================================


async def test_layer1_same_mail_twice_one_proposal(db):
    """Cùng 1 mail xử lý 2 lần → chỉ 1 proposal (lớp dedup message_id)."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<qa09-l1-1@maersk.com>")
    extract = fake_extract(make_extraction())

    first = await process_raw_email(
        raw, session_factory=db, extract=extract, broadcast=AsyncMock()
    )
    assert first.outcome == "proposals_created"
    assert await _proposal_count(db) == 1

    second = await process_raw_email(
        raw, session_factory=db, extract=extract, broadcast=AsyncMock()
    )
    # Layer-1 dedup: outcome None (no write), no new proposal, no new processed row.
    assert second.outcome is None
    assert second.proposal_ids == ()
    assert await _proposal_count(db) == 1
    assert await _processed_count(db) == 1


async def test_layer1_dedup_short_circuits_before_llm(db):
    """Lớp 1 chặn TRƯỚC extract: lần 2 KHÔNG gọi LLM (spy.assert_not_awaited)."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<qa09-l1-2@maersk.com>")
    await process_raw_email(
        raw, session_factory=db, extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    extract_spy = AsyncMock()
    result = await process_raw_email(
        raw, session_factory=db, extract=extract_spy, broadcast=AsyncMock()
    )
    assert result.outcome is None
    extract_spy.assert_not_awaited()


async def test_layer1_dedup_preserves_needs_seen_when_seen_null(db):
    """Dedup skip vẫn báo needs_seen nếu seen_set_at NULL (để poll retry STORE)."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<qa09-l1-3@maersk.com>")
    # Record processed row WITHOUT seen_set_at (simulate prior \Seen failure).
    await process_raw_email(
        raw, session_factory=db, extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    # seen_set_at is NULL because process_raw_email never sets it (poll does).
    async with db() as session:
        row = await session.get(ProcessedEmail, "<qa09-l1-3@maersk.com>")
        assert row.seen_set_at is None

    again = await process_raw_email(
        raw, session_factory=db, extract=AsyncMock(), broadcast=AsyncMock()
    )
    assert again.outcome is None
    assert again.needs_seen is True  # NULL seen → still needs STORE retry


# ===========================================================================
# GROUP 2 — Idempotency LAYER 2: DB unique (source_email_id, shipment_id)
#   Simulate the row leaking (delete processed_emails) so extract re-runs, then
#   assert no duplicate proposal is created; and directly prove the constraint
#   raises IntegrityError on a forced duplicate insert.
# ===========================================================================


async def test_layer2_reprocess_after_row_deleted_no_dup_proposal(db):
    """Lọt lớp 1 (xóa dòng processed_emails) → lớp 2 chặn: proposal KHÔNG tăng.

    Cơ chế thật (email_service.py:146-153): pre-SELECT dup theo
    (source_email_id, shipment_id) trước INSERT → bỏ qua container đã có proposal
    → outcome='no_match' (không proposal mới), count vẫn = 1.
    """
    await seed_shipment(db)
    raw = make_raw_email(message_id="<qa09-l2-1@maersk.com>")
    extract = fake_extract(make_extraction())

    r1 = await process_raw_email(
        raw, session_factory=db, extract=extract, broadcast=AsyncMock()
    )
    assert r1.outcome == "proposals_created"
    assert await _proposal_count(db) == 1

    # Simulate the processed_emails guard leaking (row gone) — LLM WILL re-run.
    async with db() as session:
        async with session.begin():
            await session.execute(
                delete(ProcessedEmail).where(
                    ProcessedEmail.message_id == "<qa09-l2-1@maersk.com>"
                )
            )

    extract_spy = AsyncMock(return_value=make_extraction())
    r2 = await process_raw_email(
        raw, session_factory=db, extract=extract_spy, broadcast=AsyncMock()
    )
    # Extract DID run this time (layer-1 bypassed), proving layer-2 is what holds.
    extract_spy.assert_awaited_once()
    assert r2.proposal_ids == ()
    assert r2.outcome == "no_match"  # container đã có proposal → không tạo mới
    assert await _proposal_count(db) == 1  # KHÔNG proposal trùng


async def test_layer2_db_unique_constraint_raises_on_forced_duplicate(db):
    """Chứng minh constraint DB thật: INSERT trùng (source_email_id, shipment_id)
    → IntegrityError (UNIQUE). Đây là backstop của lớp 2."""
    sid, _ = await seed_shipment(db)
    raw = make_raw_email(message_id="<qa09-l2-2@maersk.com>")
    await process_raw_email(
        raw, session_factory=db, extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    with pytest.raises(IntegrityError):
        async with db() as session:
            async with session.begin():
                session.add(
                    AgentProposal(
                        shipment_id=sid,
                        source_email_id="<qa09-l2-2@maersk.com>",
                        extracted_json={},
                        proposed_action="eta_update",
                    )
                )


async def test_layer2_partial_unique_allows_null_shipment(db):
    """Partial index WHERE shipment_id IS NOT NULL: nhiều proposal shipment_id=NULL
    (no_match trace) KHÔNG bị unique chặn — kiểm không siết nhầm."""
    # Two DISTINCT emails, both with no matching container → each records a
    # processed_emails row with outcome no_match; and a manual NULL-shipment
    # proposal insert twice must NOT collide.
    async with db() as session:
        async with session.begin():
            session.add(
                AgentProposal(
                    shipment_id=None, source_email_id="<null-a@x.com>",
                    extracted_json={}, proposed_action="eta_update",
                )
            )
            session.add(
                AgentProposal(
                    shipment_id=None, source_email_id="<null-a@x.com>",
                    extracted_json={}, proposed_action="eta_update",
                )
            )
    # No IntegrityError → partial predicate excludes NULL rows (correct).
    async with db() as session:
        n = (
            await session.execute(
                select(func.count(AgentProposal.id)).where(
                    AgentProposal.shipment_id.is_(None)
                )
            )
        ).scalar_one()
        assert n == 2


async def test_layer2_two_shipments_one_proposal_each_stable_on_replay(db):
    """1 mail, 2 lô khớp → 2 proposal; replay cùng mail → vẫn 2 (không nhân đôi)."""
    await seed_shipment(db, container_no="MSKU1234565", bl_number="BL-1")
    await seed_shipment(db, container_no="WHLU5500123", bl_number="BL-4")
    extraction = make_extraction(containers=["MSKU1234565", "WHLU5500123"])
    raw = make_raw_email(message_id="<qa09-l2-3@maersk.com>")

    await process_raw_email(
        raw, session_factory=db, extract=fake_extract(extraction), broadcast=AsyncMock()
    )
    # Delete processed row to force layer-1 bypass on replay.
    async with db() as session:
        async with session.begin():
            await session.execute(
                delete(ProcessedEmail).where(
                    ProcessedEmail.message_id == "<qa09-l2-3@maersk.com>"
                )
            )
    await process_raw_email(
        raw, session_factory=db, extract=fake_extract(extraction), broadcast=AsyncMock()
    )
    assert await _proposal_count(db) == 2


# ===========================================================================
# GROUP 3 — Allowlist kép suffix-match (A domain / B forwarder) — §7.4, IC§8
# ===========================================================================


@pytest.mark.parametrize(
    ("address", "expected", "why"),
    [
        # (A) domain hãng — exact + subdomain suffix-match
        ("noreply@maersk.com", True, "A exact domain"),
        ("alert@notification.maersk.com", True, "A subdomain suffix-match"),
        ("x@msc.com", True, "A exact msc"),
        ("x@one-line.com", True, "A exact one-line"),
        ("x@wanhai.com", True, "A exact wanhai"),
        ("x@evergreen-line.com", True, "A exact evergreen"),
        # suffix-match KHÔNG phải substring / prefix spoof
        ("x@fakemaersk.com", False, "fakemaersk.com != *.maersk.com"),
        ("x@evilmaersk.com", False, "evilmaersk not subdomain of maersk.com"),
        ("x@maersk.com.attacker.io", False, "suffix must end at domain boundary"),
        ("x@notmaersk.com", False, "prefix spoof"),
        # (B) forwarder — full-address match only
        ("ops@uandi.example.com", True, "B full forwarder address"),
        ("OPS@UANDI.EXAMPLE.COM", True, "B case-insensitive"),
        ("other@uandi.example.com", False, "B not the configured address"),
        # neither list
        ("x@gmail.com", False, "outside both lists"),
        ("not-an-email", False, "no @ → reject"),
        ("", False, "empty → reject"),
    ],
)
def test_allowlist_dual_suffix_match(address, expected, why):
    assert (
        is_allowlisted(
            address,
            carrier_domains=CARRIER_DOMAINS,
            forwarder_emails=FORWARDER_EMAILS,
        )
        is expected
    ), why


async def test_allowlist_subdomain_pass_notification_maersk(db):
    """notification.maersk.com PASS với entry maersk.com — end-to-end proposal."""
    await seed_shipment(db)
    raw = make_raw_email(
        message_id="<qa09-al-1@notification.maersk.com>",
        from_address="alert@notification.maersk.com",
    )
    result = await process_raw_email(
        raw,
        session_factory=db,
        extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
        carrier_domains=CARRIER_DOMAINS,
        forwarder_emails=FORWARDER_EMAILS,
    )
    assert result.outcome == "proposals_created"


async def test_allowlist_fakemaersk_rejected_with_trace_row(db):
    """fakemaersk.com FAIL → outcome='rejected_allowlist', vẫn ghi dòng trace,
    KHÔNG gọi LLM."""
    extract_spy = AsyncMock()
    raw = make_raw_email(
        message_id="<qa09-al-2@fakemaersk.com>",
        from_address="phish@fakemaersk.com",
    )
    result = await process_raw_email(
        raw,
        session_factory=db,
        extract=extract_spy,
        broadcast=AsyncMock(),
        carrier_domains=CARRIER_DOMAINS,
        forwarder_emails=FORWARDER_EMAILS,
    )
    assert result.outcome == "rejected_allowlist"
    extract_spy.assert_not_awaited()  # rejected before extract (§7.2 untrusted)
    async with db() as session:
        row = await session.get(ProcessedEmail, "<qa09-al-2@fakemaersk.com>")
        assert row is not None  # trace row ghi lại
        assert row.outcome == "rejected_allowlist"


async def test_allowlist_B_forwarder_full_address_match(db):
    """Allowlist B (forwarder nội bộ) match theo email đầy đủ → vẫn tạo proposal."""
    await seed_shipment(db, container_no="TEMU8123455", bl_number="BL-2")
    raw = make_raw_email(
        message_id="<qa09-al-3@uandi.example.com>",
        from_address="ops@uandi.example.com",
    )
    result = await process_raw_email(
        raw,
        session_factory=db,
        extract=fake_extract(make_extraction(containers=["TEMU8123455"])),
        broadcast=AsyncMock(),
        carrier_domains=CARRIER_DOMAINS,
        forwarder_emails=FORWARDER_EMAILS,
    )
    assert result.outcome == "proposals_created"


async def test_allowlist_outside_both_lists_rejected(db):
    """Mail ngoài cả A và B → rejected_allowlist, vẫn ghi dòng trace."""
    raw = make_raw_email(
        message_id="<qa09-al-4@gmail.com>", from_address="stranger@gmail.com"
    )
    result = await process_raw_email(
        raw,
        session_factory=db,
        extract=AsyncMock(),
        broadcast=AsyncMock(),
        carrier_domains=CARRIER_DOMAINS,
        forwarder_emails=FORWARDER_EMAILS,
    )
    assert result.outcome == "rejected_allowlist"
    async with db() as session:
        row = await session.get(ProcessedEmail, "<qa09-al-4@gmail.com>")
        assert row.outcome == "rejected_allowlist"


# ===========================================================================
# GROUP 4 — Mail 3 (IC§14): nhiều container + 1 lạ → proposal cho khớp,
#   lạ → unmatched_containers (log, không crash, không chặn), outcome
#   proposals_created (KHÔNG partial_match).
# ===========================================================================


async def test_mail3_multi_container_one_unknown(db):
    """2 container khớp + 1 lạ (không có trong hệ) → 2 proposal + 1 unmatched."""
    await seed_shipment(db, container_no="MSKU1234565", bl_number="BL-1")
    await seed_shipment(db, container_no="WHLU5500123", bl_number="BL-4")
    extraction = make_extraction(
        containers=["MSKU1234565", "ZZZU9999992", "WHLU5500123"]
    )
    result = await process_raw_email(
        make_raw_email(message_id="<qa09-m3-1@maersk.com>"),
        session_factory=db,
        extract=fake_extract(extraction),
        broadcast=AsyncMock(),
    )
    assert result.outcome == "proposals_created"  # NOT partial_match
    assert len(result.proposal_ids) == 2
    async with db() as session:
        row = await session.get(ProcessedEmail, "<qa09-m3-1@maersk.com>")
        assert row.unmatched_containers == ["ZZZU9999992"]
        # 2 matched proposals, unknown NOT among them
        sids = (
            (
                await session.execute(
                    select(AgentProposal.shipment_id).where(
                        AgentProposal.source_email_id == "<qa09-m3-1@maersk.com>"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(sids) == 2
        assert None not in sids


async def test_mail3_unknown_does_not_block_matched(db):
    """Container lạ đứng TRƯỚC vẫn không chặn container khớp phía sau."""
    await seed_shipment(db, container_no="WHLU5500123", bl_number="BL-4")
    extraction = make_extraction(containers=["ZZZU9999992", "WHLU5500123"])
    result = await process_raw_email(
        make_raw_email(message_id="<qa09-m3-2@maersk.com>"),
        session_factory=db,
        extract=fake_extract(extraction),
        broadcast=AsyncMock(),
    )
    assert result.outcome == "proposals_created"
    assert len(result.proposal_ids) == 1
    async with db() as session:
        row = await session.get(ProcessedEmail, "<qa09-m3-2@maersk.com>")
        assert row.unmatched_containers == ["ZZZU9999992"]


async def test_mail3_invalid_checkdigit_is_unmatched_not_crash(db):
    """Container sai ISO 6346 → rơi nhánh unmatched (không crash, không proposal)."""
    await seed_shipment(db)
    extraction = make_extraction(containers=["MSKU1234565", "AAAA1111111"])
    result = await process_raw_email(
        make_raw_email(message_id="<qa09-m3-3@maersk.com>"),
        session_factory=db,
        extract=fake_extract(extraction),
        broadcast=AsyncMock(),
    )
    assert result.outcome == "proposals_created"
    assert len(result.proposal_ids) == 1
    async with db() as session:
        row = await session.get(ProcessedEmail, "<qa09-m3-3@maersk.com>")
        assert row.unmatched_containers == ["AAAA1111111"]


async def test_mail3_all_unknown_is_no_match(db):
    """Mọi container đều lạ → no_match (proposal_ids rỗng), unmatched vẫn ghi."""
    extraction = make_extraction(containers=["ZZZU9999992", "WHLU5500123"])
    result = await process_raw_email(
        make_raw_email(message_id="<qa09-m3-4@maersk.com>"),
        session_factory=db,
        extract=fake_extract(extraction),
        broadcast=AsyncMock(),
    )
    assert result.outcome == "no_match"
    assert result.proposal_ids == ()
    async with db() as session:
        row = await session.get(ProcessedEmail, "<qa09-m3-4@maersk.com>")
        assert set(row.unmatched_containers) == {"ZZZU9999992", "WHLU5500123"}


async def test_mail3_from_real_fixture_eml(db):
    """Mail 3 fixture .eml thật (offline parse): 2 khớp + ZZZU9999992 lạ."""
    await seed_shipment(db, container_no="MSKU1234565", bl_number="BL-1")
    await seed_shipment(db, container_no="WHLU5500123", bl_number="BL-4")
    raw = load_fixture("mail3_multi_container.eml")
    assert raw.from_address == "noreply@maersk.com"
    assert "ZZZU9999992" in raw.body_text
    extraction = make_extraction(
        containers=["MSKU1234565", "ZZZU9999992", "WHLU5500123"],
        email_type="other",
    )
    result = await process_raw_email(
        raw, session_factory=db, extract=fake_extract(extraction), broadcast=AsyncMock()
    )
    assert result.outcome == "proposals_created"
    assert len(result.proposal_ids) == 2
    async with db() as session:
        row = await session.get(ProcessedEmail, raw.message_id)
        assert row.unmatched_containers == ["ZZZU9999992"]


# ===========================================================================
# GROUP 5 — Commit order: processed_emails INSERT TRƯỚC STORE \Seen.
#   Two failure directions:
#     (a) Seen-fail-after-insert → seen_set_at NULL, next poll dedup + retry STORE,
#         no reprocess.
#     (b) DB-insert-fail (extract explodes) → no row, \Seen NOT stored → mail refetch
#         (không mất mail).
# ===========================================================================


async def test_order_commit_before_store_seen(db):
    """Khi store_seen được gọi, dòng processed_emails ĐÃ commit (thứ tự đúng)."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<qa09-ord-1@maersk.com>")
    imap = make_imap([raw])
    seen_snapshot = {}

    async def store_seen_spy(uid):
        async with db() as session:
            seen_snapshot["row"] = await session.get(
                ProcessedEmail, "<qa09-ord-1@maersk.com>"
            )

    imap.store_seen.side_effect = store_seen_spy
    count = await poll_once(
        imap, session_factory=db, extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    assert count == 1
    imap.store_seen.assert_awaited_once_with(1)
    assert seen_snapshot["row"] is not None
    assert seen_snapshot["row"].outcome == "proposals_created"
    async with db() as session:
        row = await session.get(ProcessedEmail, "<qa09-ord-1@maersk.com>")
        assert row.seen_set_at is not None  # filled only AFTER store succeeded


async def test_order_seen_fail_after_insert_leaves_seen_null(db):
    """Seen-fail-sau-insert → row tồn tại, seen_set_at=NULL (poll sau retry)."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<qa09-ord-2@maersk.com>")
    imap = make_imap([raw])
    imap.store_seen.side_effect = ExternalIntegrationError("IMAP down", retryable=True)

    count = await poll_once(
        imap, session_factory=db, extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    assert count == 1  # mail vẫn xử lý + commit (không mất)
    async with db() as session:
        row = await session.get(ProcessedEmail, "<qa09-ord-2@maersk.com>")
        assert row is not None
        assert row.seen_set_at is None  # chưa set → poll sau retry


async def test_order_next_poll_retries_seen_without_reprocess(db):
    """Poll sau refetch cùng mail: dedup KHÔNG reprocess, chỉ retry STORE \\Seen."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<qa09-ord-3@maersk.com>")

    imap1 = make_imap([raw])
    imap1.store_seen.side_effect = ExternalIntegrationError("down", retryable=True)
    await poll_once(
        imap1, session_factory=db, extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )

    imap2 = make_imap([raw])  # mail vẫn UNSEEN → refetch, \Seen giờ OK
    extract_spy = AsyncMock()
    count = await poll_once(
        imap2, session_factory=db, extract=extract_spy, broadcast=AsyncMock()
    )
    assert count == 0  # dedup skip — không tính là mail mới
    extract_spy.assert_not_awaited()  # KHÔNG gọi LLM lại
    imap2.store_seen.assert_awaited_once_with(1)
    async with db() as session:
        row = await session.get(ProcessedEmail, "<qa09-ord-3@maersk.com>")
        assert row.seen_set_at is not None  # retry đã điền
    assert await _proposal_count(db) == 1  # không tạo trùng


async def test_order_db_fail_leaves_no_row_and_mail_unseen(db):
    """Chiều ngược: DB/extract fail (unexpected) → không row, \\Seen KHÔNG store
    → mail còn UNSEEN, refetch poll sau (không mất mail)."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<qa09-ord-4@maersk.com>")
    imap = make_imap([raw])

    async def exploding_extract(subject, body):
        raise RuntimeError("simulated DB/extract boom before insert")

    with pytest.raises(RuntimeError):
        await poll_once(
            imap, session_factory=db, extract=exploding_extract, broadcast=AsyncMock()
        )
    imap.store_seen.assert_not_awaited()  # \Seen KHÔNG store khi chưa commit
    async with db() as session:
        assert await session.get(ProcessedEmail, "<qa09-ord-4@maersk.com>") is None


async def test_order_already_seen_mail_not_restored(db):
    """Mail đã processed + seen_set_at đã điền mà bị refetch → KHÔNG store lại."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<qa09-ord-5@maersk.com>")
    imap1 = make_imap([raw])
    await poll_once(
        imap1, session_factory=db, extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    imap2 = make_imap([raw])
    await poll_once(imap2, session_factory=db, extract=AsyncMock(), broadcast=AsyncMock())
    imap2.store_seen.assert_not_awaited()


# ===========================================================================
# GROUP 6 — 4 outcome đúng luật IC§2.2 [v0.9.12]: proposals_created / no_match /
#   rejected_allowlist / parse_failed. KHÔNG có giá trị thứ 5 (partial_match).
# ===========================================================================


def test_exactly_four_outcomes_no_partial_match():
    """Enum EMAIL_OUTCOME đúng 4 giá trị, KHÔNG partial_match ([v0.9.12])."""
    assert set(EMAIL_OUTCOME) == {
        "proposals_created",
        "no_match",
        "rejected_allowlist",
        "parse_failed",
    }
    assert "partial_match" not in EMAIL_OUTCOME
    assert len(EMAIL_OUTCOME) == 4


async def test_outcome_proposals_created(db):
    await seed_shipment(db)
    result = await process_raw_email(
        make_raw_email(message_id="<qa09-o1@maersk.com>"),
        session_factory=db,
        extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    assert result.outcome == "proposals_created"


async def test_outcome_no_match(db):
    result = await process_raw_email(
        make_raw_email(message_id="<qa09-o2@maersk.com>"),
        session_factory=db,
        extract=fake_extract(make_extraction()),  # container not seeded
        broadcast=AsyncMock(),
    )
    assert result.outcome == "no_match"


async def test_outcome_rejected_allowlist(db):
    result = await process_raw_email(
        make_raw_email(message_id="<qa09-o3@gmail.com>", from_address="a@gmail.com"),
        session_factory=db,
        extract=AsyncMock(),
        broadcast=AsyncMock(),
        carrier_domains=CARRIER_DOMAINS,
        forwarder_emails=FORWARDER_EMAILS,
    )
    assert result.outcome == "rejected_allowlist"


async def test_outcome_parse_failed(db):
    """Parse hỏng (LLM fail sau retry) → parse_failed, ghi trace, không crash."""
    async def failing_extract(subject, body):
        raise EmailParseError("bad LLM output twice")

    result = await process_raw_email(
        make_raw_email(message_id="<qa09-o4@maersk.com>"),
        session_factory=db,
        extract=failing_extract,
        broadcast=AsyncMock(),
    )
    assert result.outcome == "parse_failed"
    async with db() as session:
        row = await session.get(ProcessedEmail, "<qa09-o4@maersk.com>")
        assert row.outcome == "parse_failed"


async def test_every_recorded_outcome_satisfies_check_constraint(db):
    """Mọi outcome ghi vào DB nằm trong CHECK enum (không giá trị lạ)."""
    await seed_shipment(db, container_no="MSKU1234565", bl_number="BL-1")

    async def failing_extract(subject, body):
        raise EmailParseError("boom")

    scenarios = [
        (make_raw_email(message_id="<qa09-c1@maersk.com>"),
         fake_extract(make_extraction()), None, None),  # proposals_created
        (make_raw_email(message_id="<qa09-c2@maersk.com>"),
         fake_extract(make_extraction(containers=["ZZZU9999992"])), None, None),  # no_match
        (make_raw_email(message_id="<qa09-c3@gmail.com>", from_address="a@gmail.com"),
         AsyncMock(), CARRIER_DOMAINS, FORWARDER_EMAILS),  # rejected_allowlist
        (make_raw_email(message_id="<qa09-c4@maersk.com>"),
         failing_extract, None, None),  # parse_failed
    ]
    for raw, extract, cd, fe in scenarios:
        await process_raw_email(
            raw, session_factory=db, extract=extract, broadcast=AsyncMock(),
            carrier_domains=cd, forwarder_emails=fe,
        )
    async with db() as session:
        outcomes = (
            (await session.execute(select(ProcessedEmail.outcome))).scalars().all()
        )
    assert set(outcomes) <= set(EMAIL_OUTCOME)
    assert set(outcomes) == {
        "proposals_created", "no_match", "rejected_allowlist", "parse_failed",
    }


# ===========================================================================
# GROUP 7 — SUSPECT path: async correctness. Run mocks with correct async
#   signature under -W error::RuntimeWarning to catch un-awaited coroutines.
#   Also asserts human-in-the-loop (§7.2): service never mutates shipment.
# ===========================================================================


@pytest.mark.filterwarnings("error::RuntimeWarning")
async def test_suspect_extract_awaited_no_runtimewarning(db):
    """extract mock có async signature đúng → không RuntimeWarning coroutine-un-awaited."""
    await seed_shipment(db)
    extract_spy = AsyncMock(return_value=make_extraction())
    result = await process_raw_email(
        make_raw_email(message_id="<qa09-susp-1@maersk.com>"),
        session_factory=db,
        extract=extract_spy,
        broadcast=AsyncMock(),
    )
    assert result.outcome == "proposals_created"
    extract_spy.assert_awaited_once()


@pytest.mark.filterwarnings("error::RuntimeWarning")
async def test_suspect_poll_all_awaits_clean(db):
    """poll_once path (fetch/store_seen/broadcast) đều await đúng — no warning."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<qa09-susp-2@maersk.com>")
    imap = make_imap([raw])
    broadcast = AsyncMock()
    count = await poll_once(
        imap, session_factory=db, extract=fake_extract(make_extraction()),
        broadcast=broadcast,
    )
    assert count == 1
    imap.fetch_unseen.assert_awaited_once()
    imap.store_seen.assert_awaited_once()
    broadcast.assert_awaited_once()


async def test_human_in_the_loop_service_never_mutates_shipment(db):
    """§7.2: service CHỈ tạo proposal (pending) — KHÔNG đụng eta_current/status/leg."""
    sid, _ = await seed_shipment(db)
    async with db() as session:
        before = await session.get(Shipment, sid)
        snap = (before.eta_current, before.status, before.vessel_name, before.voyage_no)
    await process_raw_email(
        make_raw_email(message_id="<qa09-hitl-1@maersk.com>"),
        session_factory=db,
        extract=fake_extract(
            make_extraction(new_vessel_name="EVER ACE", email_type="rollover")
        ),
        broadcast=AsyncMock(),
    )
    async with db() as session:
        after = await session.get(Shipment, sid)
        assert (after.eta_current, after.status, after.vessel_name, after.voyage_no) == snap
        proposal = (
            await session.execute(
                select(AgentProposal).where(
                    AgentProposal.source_email_id == "<qa09-hitl-1@maersk.com>"
                )
            )
        ).scalar_one()
        assert proposal.status == "pending"  # chờ người duyệt


async def test_rollover_proposed_action_from_new_vessel_name(db):
    """new_vessel_name có → proposed_action='rollover'; không có → 'eta_update'."""
    await seed_shipment(db, container_no="MSKU1234565", bl_number="BL-1")
    r_roll = await process_raw_email(
        make_raw_email(message_id="<qa09-act-1@maersk.com>"),
        session_factory=db,
        extract=fake_extract(
            make_extraction(new_vessel_name="EVER ACE", email_type="rollover")
        ),
        broadcast=AsyncMock(),
    )
    await seed_shipment(db, container_no="WHLU5500123", bl_number="BL-4")
    r_eta = await process_raw_email(
        make_raw_email(message_id="<qa09-act-2@maersk.com>"),
        session_factory=db,
        extract=fake_extract(make_extraction(containers=["WHLU5500123"])),
        broadcast=AsyncMock(),
    )
    async with db() as session:
        p_roll = await session.get(AgentProposal, r_roll.proposal_ids[0])
        p_eta = await session.get(AgentProposal, r_eta.proposal_ids[0])
        assert p_roll.proposed_action == "rollover"
        assert p_eta.proposed_action == "eta_update"


async def test_extracted_json_keeps_full_container_list(db):
    """IC§4.2: extracted_json giữ NGUYÊN list container gốc (kể cả lạ) để người duyệt
    thấy toàn cảnh — không cắt theo container khớp."""
    await seed_shipment(db, container_no="MSKU1234565", bl_number="BL-1")
    extraction = make_extraction(
        containers=["MSKU1234565", "ZZZU9999992", "WHLU5500123"]
    )
    result = await process_raw_email(
        make_raw_email(message_id="<qa09-json-1@maersk.com>"),
        session_factory=db,
        extract=fake_extract(extraction),
        broadcast=AsyncMock(),
    )
    async with db() as session:
        proposal = await session.get(AgentProposal, result.proposal_ids[0])
        assert proposal.extracted_json["containers"] == [
            "MSKU1234565", "ZZZU9999992", "WHLU5500123",
        ]
