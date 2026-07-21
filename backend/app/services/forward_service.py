"""Auto-forward theo monitoring_mode (§7.4, IC§7) — SMTP outbound whitelist-only.

Rào an toàn (hard gate, §7.4): recipient CHỈ từ ``AUTO_FORWARD_RECIPIENTS`` env —
``auto_forward`` KHÔNG nhận tham số recipient và KHÔNG BAO GIỜ đọc To/CC/Reply-To
từ nội dung mail (mail là untrusted input §7.2 — chống kênh rò rỉ dữ liệu).
Mọi lần forward đều log audit: recipient, message_id, shipment_id, timestamp.
SMTP fail → log error, không raise xuyên lên poll loop (fallback êm).
"""

import logging
from datetime import UTC, datetime
from email.message import EmailMessage

import aiosmtplib

from app.config import settings
from app.db.models import Shipment
from app.integrations.imap_client import RawEmail

logger = logging.getLogger(__name__)

SMTP_PORT = 587  # submission + STARTTLS
SMTP_TIMEOUT_SECONDS = 30.0


def derive_smtp_host(imap_host: str) -> str:
    """IC§7 chỉ có IMAP host — suy SMTP host cùng provider (imap.x → smtp.x)."""
    if imap_host.startswith("imap."):
        return "smtp." + imap_host.removeprefix("imap.")
    return imap_host


def _parse_recipients(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


async def auto_forward(email: RawEmail, shipment: Shipment) -> bool:
    """Forward one carrier mail to the pre-configured internal whitelist.

    Returns True only when the mail was actually sent. Never raises.
    """
    if shipment.monitoring_mode != "auto_email":  # defense in depth — không tin caller
        return False

    recipients = _parse_recipients(settings.AUTO_FORWARD_RECIPIENTS)
    if not recipients:
        logger.info(
            "auto_forward skipped (AUTO_FORWARD_RECIPIENTS trống) message_id=%s shipment_id=%s",
            email.message_id,
            shipment.id,
        )
        return False
    if not settings.DELEGATE_MAILBOX_IMAP_HOST:
        logger.info(
            "auto_forward skipped (delegate mailbox chưa cấu hình) message_id=%s shipment_id=%s",
            email.message_id,
            shipment.id,
        )
        return False

    message = EmailMessage()
    message["From"] = settings.DELEGATE_MAILBOX_USER
    message["To"] = ", ".join(recipients)
    message["Subject"] = f"[Auto-forward] {email.subject}"
    message.set_content(
        f"Auto-forwarded carrier notification (shipment_id={shipment.id}, "
        f"source message_id={email.message_id}).\n\n"
        f"--- Original mail ---\n"
        f"From: {email.from_address}\n"
        f"Subject: {email.subject}\n\n"
        f"{email.body_text}"
    )

    host = derive_smtp_host(settings.DELEGATE_MAILBOX_IMAP_HOST)
    try:
        await aiosmtplib.send(
            message,
            recipients=recipients,
            hostname=host,
            port=SMTP_PORT,
            start_tls=True,
            username=settings.DELEGATE_MAILBOX_USER,
            password=settings.DELEGATE_MAILBOX_PASSWORD,
            timeout=SMTP_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — fallback êm, không crash poll loop
        logger.error(
            "auto_forward failed (SMTP) message_id=%s shipment_id=%s host=%s: %s",
            email.message_id,
            shipment.id,
            host,
            exc,
        )
        return False

    logger.info(
        "auto_forward sent recipient=%s message_id=%s shipment_id=%s ts=%s",
        settings.AUTO_FORWARD_RECIPIENTS,
        email.message_id,
        shipment.id,
        datetime.now(UTC).isoformat(),
    )
    return True
