"""Email Agent business service (§7.1/§7.2/§7.4) — allowlist, dedup, proposals.

Transaction order (Patch p2, PROGRESS.md TASK-13): the ``processed_emails`` row
(+ proposals) is committed BEFORE ``STORE \\Seen``. If the flag store fails the
next poll refetches the mail, dedup skips reprocessing, and the ``\\Seen`` store
is retried (``seen_set_at`` NULL → filled). The reverse order could lose mail
forever, so it is forbidden.

Human-in-the-loop (§7.2): mail is untrusted input — this service ONLY creates
``agent_proposals`` rows; nothing here touches ``eta_current`` or legs.

All IMAP I/O goes through ``IMAPClient`` and all LLM I/O through
``email_agent`` (Decision 0005) — no imaplib/httpx imports here.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.agents import email_agent
from app.agents.email_agent import EmailParseError
from app.config import settings
from app.core.normalize import normalize_container_no
from app.db.base import async_session_factory
from app.db.models import AgentProposal, ProcessedEmail, Shipment
from app.integrations.errors import ExternalIntegrationError
from app.integrations.imap_client import IMAPClient, RawEmail
from app.services import forward_service
from app.services.broadcast import broadcast_proposal_created

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailProcessResult:
    """In-memory result of one mail. ``outcome`` None = dedup skip (no write)."""

    outcome: str | None
    needs_seen: bool
    proposal_ids: tuple[int, ...] = ()


def _split_csv(raw: str) -> list[str]:
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def is_allowlisted(
    from_address: str,
    *,
    carrier_domains: list[str] | None = None,
    forwarder_emails: list[str] | None = None,
) -> bool:
    """Dual allowlist §7.4: (A) carrier domain suffix-match OR (B) internal forwarder."""
    address = (from_address or "").strip().lower()
    if "@" not in address:
        return False
    if carrier_domains is None:
        carrier_domains = _split_csv(settings.CARRIER_EMAIL_DOMAINS)
    if forwarder_emails is None:
        forwarder_emails = _split_csv(settings.INTERNAL_FORWARDER_EMAILS)

    if address in forwarder_emails:
        return True
    from_domain = address.rsplit("@", 1)[1]
    return any(
        from_domain == domain or from_domain.endswith("." + domain)
        for domain in carrier_domains
    )


async def process_raw_email(
    raw: RawEmail,
    *,
    session_factory=async_session_factory,
    extract=email_agent.extract_email,
    broadcast=broadcast_proposal_created,
    carrier_domains: list[str] | None = None,
    forwarder_emails: list[str] | None = None,
) -> EmailProcessResult:
    """Process one mail through dedup → allowlist → extract → match → proposals.

    Commits ``processed_emails`` (+ proposals) in ONE transaction and does NOT
    touch the ``\\Seen`` flag — the caller stores the flag only after this
    commit succeeded (Patch p2 ordering).
    """
    async with session_factory() as session:
        existing = await session.get(ProcessedEmail, raw.message_id)
        if existing is not None:
            return EmailProcessResult(outcome=None, needs_seen=existing.seen_set_at is None)

    if not is_allowlisted(
        raw.from_address,
        carrier_domains=carrier_domains,
        forwarder_emails=forwarder_emails,
    ):
        await _record(session_factory, raw, "rejected_allowlist", None)
        return EmailProcessResult(outcome="rejected_allowlist", needs_seen=True)

    try:
        extraction = await extract(raw.subject, raw.body_text)
    except EmailParseError as exc:
        logger.warning("email %s parse_failed after retry: %s", raw.message_id, exc)
        await _record(session_factory, raw, "parse_failed", None)
        return EmailProcessResult(outcome="parse_failed", needs_seen=True)

    valid_containers: list[str] = []
    unmatched: list[str] = []
    for raw_container in extraction.containers:
        try:
            valid_containers.append(normalize_container_no(raw_container))
        except ValueError:
            # Fail check-digit/format = "container lạ" (§7.1) — log, no proposal.
            logger.info(
                "email %s: container lạ (sai ISO 6346) %r", raw.message_id, raw_container
            )
            unmatched.append(raw_container)

    extracted_payload = extraction.model_dump(mode="json")
    proposed_action = "rollover" if extraction.new_vessel_name else "eta_update"
    proposal_ids: list[int] = []
    broadcast_payloads: list[tuple[int, dict]] = []
    forward_shipments: list[Shipment] = []

    async with session_factory() as session:
        async with session.begin():
            matched_by_container: dict[str, Shipment] = {}
            if valid_containers:
                rows = await session.execute(
                    select(Shipment).where(Shipment.container_no.in_(valid_containers))
                )
                for shipment in rows.scalars():
                    matched_by_container[shipment.container_no] = shipment

            for container in valid_containers:
                if container not in matched_by_container:
                    logger.info(
                        "email %s: container lạ (không có trong hệ) %r",
                        raw.message_id,
                        container,
                    )
                    unmatched.append(container)

            for container, shipment in matched_by_container.items():
                dup = await session.execute(
                    select(AgentProposal.id)
                    .where(AgentProposal.source_email_id == raw.message_id)
                    .where(AgentProposal.shipment_id == shipment.id)
                )
                if dup.scalar_one_or_none() is not None:
                    continue
                proposal = AgentProposal(
                    shipment_id=shipment.id,
                    source_email_id=raw.message_id,
                    extracted_json=extracted_payload,
                    proposed_action=proposed_action,
                )
                session.add(proposal)
                await session.flush()
                proposal_ids.append(proposal.id)
                if shipment.monitoring_mode == "auto_email":
                    forward_shipments.append(shipment)
                broadcast_payloads.append(
                    (
                        shipment.id,
                        {
                            "proposal_id": proposal.id,
                            "proposed_action": proposed_action,
                            "email_type": extraction.email_type,
                            "container_no": container,
                        },
                    )
                )

            outcome = "proposals_created" if proposal_ids else "no_match"
            session.add(
                ProcessedEmail(
                    message_id=raw.message_id,
                    imap_uid=raw.uid,
                    imap_folder=raw.folder,
                    outcome=outcome,
                    unmatched_containers=unmatched or None,
                )
            )

    for shipment_id, payload in broadcast_payloads:
        await broadcast(shipment_id, payload)

    # TASK-16 §7.4: sau khi proposal đã commit — lô auto_email → auto-forward
    # (recipient chỉ từ env whitelist; fail chỉ log, không ảnh hưởng proposal).
    for shipment in forward_shipments:
        await forward_service.auto_forward(raw, shipment)

    return EmailProcessResult(
        outcome=outcome, needs_seen=True, proposal_ids=tuple(proposal_ids)
    )


async def _record(
    session_factory, raw: RawEmail, outcome: str, unmatched: list[str] | None
) -> None:
    async with session_factory() as session:
        async with session.begin():
            session.add(
                ProcessedEmail(
                    message_id=raw.message_id,
                    imap_uid=raw.uid,
                    imap_folder=raw.folder,
                    outcome=outcome,
                    unmatched_containers=unmatched,
                )
            )


async def _mark_seen_set(session_factory, message_id: str) -> None:
    async with session_factory() as session:
        async with session.begin():
            row = await session.get(ProcessedEmail, message_id)
            if row is not None:
                row.seen_set_at = datetime.now(UTC)


async def poll_once(
    imap: IMAPClient,
    *,
    session_factory=async_session_factory,
    extract=email_agent.extract_email,
    broadcast=broadcast_proposal_created,
) -> int:
    """One poll cycle: fetch UNSEEN, process each mail, then flag ``\\Seen``.

    Returns the number of newly processed mails. A ``\\Seen`` store failure is
    non-fatal: the row stays with ``seen_set_at`` NULL and the next poll's
    dedup branch retries the flag without reprocessing.
    """
    mails = await imap.fetch_unseen()
    processed = 0
    for raw in mails:
        result = await process_raw_email(
            raw,
            session_factory=session_factory,
            extract=extract,
            broadcast=broadcast,
        )
        if result.outcome is not None:
            processed += 1
        if result.needs_seen:
            try:
                await imap.store_seen(raw.uid)
            except ExternalIntegrationError as exc:
                logger.warning(
                    "STORE \\Seen failed for %s (uid=%s), retry next poll: %s",
                    raw.message_id,
                    raw.uid,
                    exc,
                )
                continue
            await _mark_seen_set(session_factory, raw.message_id)
    return processed


async def run() -> None:
    """Single email poller (lifespan-owned — exactly one instance, §7.1)."""
    if not settings.DELEGATE_MAILBOX_IMAP_HOST:
        logger.info("email poller disabled: DELEGATE_MAILBOX_IMAP_HOST trống")
        return
    imap = IMAPClient(
        settings.DELEGATE_MAILBOX_IMAP_HOST,
        settings.DELEGATE_MAILBOX_USER,
        settings.DELEGATE_MAILBOX_PASSWORD,
    )
    interval = max(60, settings.EMAIL_POLL_INTERVAL_MINUTES * 60)
    while True:
        try:
            count = await poll_once(imap)
            if count:
                logger.info("email poll: %d mail mới xử lý", count)
        except ExternalIntegrationError as exc:
            logger.warning("email poll failed (retry sau %ss): %s", interval, exc)
        except Exception:  # noqa: BLE001 — poller must never die (fallback êm)
            logger.exception("email poll unexpected error")
        await asyncio.sleep(interval)
