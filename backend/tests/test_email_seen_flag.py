"""TASK-13 — Patch p2 ordering: commit processed_emails TRƯỚC STORE \\Seen."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.db.models import AgentProposal, ProcessedEmail
from app.integrations.errors import ExternalIntegrationError
from app.services.email_service import poll_once, process_raw_email
from tests.email_helpers import (
    fake_extract,
    make_extraction,
    make_raw_email,
    seed_shipment,
)


def make_imap(mails):
    imap = AsyncMock()
    imap.fetch_unseen.return_value = list(mails)
    return imap


async def test_db_commit_happens_before_store_seen(db):
    """Thứ tự bắt buộc: processed_emails đã commit khi store_seen được gọi."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<order-1@maersk.com>")
    imap = make_imap([raw])
    committed_before_seen = {}

    async def store_seen_spy(uid):
        async with db() as session:
            row = await session.get(ProcessedEmail, "<order-1@maersk.com>")
            committed_before_seen["row"] = row

    imap.store_seen.side_effect = store_seen_spy

    count = await poll_once(
        imap,
        session_factory=db,
        extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    assert count == 1
    imap.store_seen.assert_awaited_once_with(1)
    assert committed_before_seen["row"] is not None
    assert committed_before_seen["row"].outcome == "proposals_created"
    # seen_set_at chỉ được điền SAU khi store thành công
    async with db() as session:
        row = await session.get(ProcessedEmail, "<order-1@maersk.com>")
        assert row.seen_set_at is not None


async def test_seen_store_failure_leaves_seen_set_at_null(db):
    await seed_shipment(db)
    raw = make_raw_email(message_id="<seenfail-1@maersk.com>")
    imap = make_imap([raw])
    imap.store_seen.side_effect = ExternalIntegrationError("IMAP down", retryable=True)

    count = await poll_once(
        imap,
        session_factory=db,
        extract=fake_extract(make_extraction()),
        broadcast=AsyncMock(),
    )
    assert count == 1  # mail vẫn được xử lý + commit
    async with db() as session:
        row = await session.get(ProcessedEmail, "<seenfail-1@maersk.com>")
        assert row is not None
        assert row.seen_set_at is None  # retry ở poll sau


async def test_next_poll_dedup_skips_and_retries_seen(db):
    """Poll sau refetch cùng mail: dedup không reprocess, chỉ retry \\Seen."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<retry-1@maersk.com>")

    # Poll 1: \Seen fail
    imap1 = make_imap([raw])
    imap1.store_seen.side_effect = ExternalIntegrationError("down", retryable=True)
    await poll_once(
        imap1, session_factory=db, extract=fake_extract(make_extraction()), broadcast=AsyncMock()
    )

    # Poll 2: mail vẫn UNSEEN → refetch; \Seen giờ OK
    imap2 = make_imap([raw])
    extract_spy = AsyncMock()
    count = await poll_once(
        imap2, session_factory=db, extract=extract_spy, broadcast=AsyncMock()
    )
    assert count == 0  # dedup skip — không tính là mail mới
    extract_spy.assert_not_awaited()  # không gọi LLM lại
    imap2.store_seen.assert_awaited_once_with(1)
    async with db() as session:
        row = await session.get(ProcessedEmail, "<retry-1@maersk.com>")
        assert row.seen_set_at is not None  # retry đã điền
        n = (await session.execute(select(func.count(AgentProposal.id)))).scalar_one()
        assert n == 1  # proposal không tăng


async def test_db_failure_leaves_mail_unseen_no_row(db):
    """Chiều ngược: DB fail → không có row, \\Seen KHÔNG được store → refetch sau."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<dbfail-1@maersk.com>")
    imap = make_imap([raw])

    async def exploding_extract(subject, body):
        raise RuntimeError("unexpected boom")

    with pytest.raises(RuntimeError):
        await poll_once(
            imap, session_factory=db, extract=exploding_extract, broadcast=AsyncMock()
        )
    imap.store_seen.assert_not_awaited()
    async with db() as session:
        assert await session.get(ProcessedEmail, "<dbfail-1@maersk.com>") is None


async def test_already_seen_processed_mail_needs_no_store(db):
    """Mail đã processed + seen_set_at đã điền mà vẫn bị refetch → không store lại."""
    await seed_shipment(db)
    raw = make_raw_email(message_id="<done-1@maersk.com>")
    imap1 = make_imap([raw])
    await poll_once(
        imap1, session_factory=db, extract=fake_extract(make_extraction()), broadcast=AsyncMock()
    )

    imap2 = make_imap([raw])
    result = await process_raw_email(
        raw, session_factory=db, extract=AsyncMock(), broadcast=AsyncMock()
    )
    assert result.needs_seen is False
    await poll_once(imap2, session_factory=db, extract=AsyncMock(), broadcast=AsyncMock())
    imap2.store_seen.assert_not_awaited()
