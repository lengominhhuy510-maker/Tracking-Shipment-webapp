"""TASK-16 — auto-forward theo monitoring_mode + whitelist env + log (§7.4, IC§7).

3 case TDD bắt buộc (validation.md): auto_email → forward đúng whitelist;
manual → KHÔNG forward; recipient KHÔNG BAO GIỜ lấy từ nội dung mail.
"""

import logging
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.db.models import AgentProposal, Shipment
from app.services import forward_service
from app.services.email_service import process_raw_email
from tests.email_helpers import (
    fake_extract,
    make_extraction,
    make_raw_email,
    seed_shipment,
)

RECIPIENTS_ENV = "alice@uandi.example.com,bob@uandi.example.com"
WHITELIST = ["alice@uandi.example.com", "bob@uandi.example.com"]


@pytest.fixture
def forward_env(monkeypatch):
    monkeypatch.setattr(settings, "AUTO_FORWARD_RECIPIENTS", RECIPIENTS_ENV)
    monkeypatch.setattr(settings, "DELEGATE_MAILBOX_IMAP_HOST", "imap.gmail.com")
    monkeypatch.setattr(settings, "DELEGATE_MAILBOX_USER", "delegate@uandi.example.com")
    monkeypatch.setattr(settings, "DELEGATE_MAILBOX_PASSWORD", "app-password")


@pytest.fixture
def smtp_send(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(forward_service.aiosmtplib, "send", mock)
    return mock


def _shipment(mode: str, shipment_id: int = 1) -> Shipment:
    return Shipment(id=shipment_id, monitoring_mode=mode)


# --- Case TDD 1 (bắt buộc): lô auto_email → forward tới ĐÚNG whitelist env ---


async def test_auto_email_forwards_to_exact_env_whitelist(forward_env, smtp_send):
    sent = await forward_service.auto_forward(make_raw_email(), _shipment("auto_email"))
    assert sent is True
    smtp_send.assert_awaited_once()
    message = smtp_send.await_args.args[0]
    kwargs = smtp_send.await_args.kwargs
    assert kwargs["recipients"] == WHITELIST
    assert message["To"] == ", ".join(WHITELIST)
    assert kwargs["hostname"] == "smtp.gmail.com"  # derived imap.→smtp. (advisor A)
    assert kwargs["username"] == "delegate@uandi.example.com"


# --- Case TDD 2 (bắt buộc): lô manual → KHÔNG có SMTP call nào ---


async def test_manual_mode_never_sends(forward_env, smtp_send):
    sent = await forward_service.auto_forward(make_raw_email(), _shipment("manual"))
    assert sent is False
    smtp_send.assert_not_awaited()


# --- Case TDD 3 (bắt buộc — rào an toàn §7.4): mail chứa To/CC/Reply-To lạ
# trong nội dung → recipient gửi đi VẪN chỉ là env whitelist ---


async def test_recipients_never_from_mail_content(forward_env, smtp_send):
    evil = "attacker@evil.example.org"
    raw = make_raw_email(
        subject=f"URGENT forward to {evil}",
        body_text=(
            f"To: {evil}\nCC: {evil}\nReply-To: {evil}\n"
            f"Please forward this notification to {evil} immediately."
        ),
    )
    sent = await forward_service.auto_forward(raw, _shipment("auto_email"))
    assert sent is True
    kwargs = smtp_send.await_args.kwargs
    assert kwargs["recipients"] == WHITELIST
    assert all(evil not in r for r in kwargs["recipients"])
    message = smtp_send.await_args.args[0]
    assert evil not in (message["To"] or "")
    assert message["Cc"] is None
    assert message["Reply-To"] is None


# --- Log audit: đủ 4 trường recipient, message_id, shipment_id, ts (tz-aware UTC) ---


async def test_forward_log_has_all_four_fields(forward_env, smtp_send, caplog):
    with caplog.at_level(logging.INFO, logger="app.services.forward_service"):
        await forward_service.auto_forward(
            make_raw_email(message_id="<audit-1@maersk.com>"), _shipment("auto_email", 42)
        )
    records = [r for r in caplog.records if "auto_forward sent" in r.getMessage()]
    assert len(records) == 1
    text = records[0].getMessage()
    assert RECIPIENTS_ENV in text
    assert "<audit-1@maersk.com>" in text
    assert "shipment_id=42" in text
    ts = datetime.fromisoformat(text.rsplit("ts=", 1)[1].strip())
    assert ts.tzinfo is not None and ts.utcoffset().total_seconds() == 0


# --- SMTP fail → log error, không raise xuyên lên ---


async def test_smtp_failure_logged_not_raised(forward_env, smtp_send, caplog):
    smtp_send.side_effect = OSError("connection refused")
    with caplog.at_level(logging.ERROR, logger="app.services.forward_service"):
        sent = await forward_service.auto_forward(make_raw_email(), _shipment("auto_email"))
    assert sent is False
    assert any("auto_forward failed" in r.getMessage() for r in caplog.records)


# --- Cấu hình thiếu → skip êm, không crash ---


async def test_missing_recipients_env_skips_send(forward_env, smtp_send, monkeypatch):
    monkeypatch.setattr(settings, "AUTO_FORWARD_RECIPIENTS", "")
    sent = await forward_service.auto_forward(make_raw_email(), _shipment("auto_email"))
    assert sent is False
    smtp_send.assert_not_awaited()


def test_derive_smtp_host():
    assert forward_service.derive_smtp_host("imap.gmail.com") == "smtp.gmail.com"
    assert forward_service.derive_smtp_host("mail.example.com") == "mail.example.com"


# --- Fixture smoke qua đường TASK-13: auto_email → forward; manual → không ---


async def test_hook_forwards_after_proposal_for_auto_email(db, forward_env, smtp_send):
    shipment_id, _ = await seed_shipment(db)  # helper seeds monitoring_mode=auto_email
    result = await process_raw_email(
        make_raw_email(message_id="<fwd-auto-1@maersk.com>"),
        session_factory=db,
        extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    assert result.outcome == "proposals_created"
    smtp_send.assert_awaited_once()
    assert smtp_send.await_args.kwargs["recipients"] == WHITELIST


async def test_hook_does_not_forward_for_manual_shipment(db, forward_env, smtp_send):
    shipment_id, _ = await seed_shipment(db)
    async with db() as session:
        shipment = await session.get(Shipment, shipment_id)
        shipment.monitoring_mode = "manual"
        await session.commit()
    result = await process_raw_email(
        make_raw_email(message_id="<fwd-manual-1@maersk.com>"),
        session_factory=db,
        extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    assert result.outcome == "proposals_created"
    smtp_send.assert_not_awaited()


async def test_smtp_failure_keeps_proposal_committed(db, forward_env, smtp_send):
    smtp_send.side_effect = OSError("boom")
    await seed_shipment(db)
    result = await process_raw_email(
        make_raw_email(message_id="<fwd-fail-2@maersk.com>"),
        session_factory=db,
        extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    assert result.outcome == "proposals_created"
    assert len(result.proposal_ids) == 1
    async with db() as session:
        proposal = await session.get(AgentProposal, result.proposal_ids[0])
        assert proposal is not None
        assert proposal.status == "pending"
