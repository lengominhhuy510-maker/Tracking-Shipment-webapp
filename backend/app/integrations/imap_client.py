"""IMAP transport boundary (Decision 0005, §7.4) — stdlib ``imaplib`` only.

Transport concerns only: connect/login/select, fetch UNSEEN by UID, STORE
``\\Seen`` by UID, RFC822 parsing into the typed ``RawEmail`` model, timeout and
error mapping to ``ExternalIntegrationError``. NO business logic, NO DB access
(email_service owns allowlist/dedup/proposals).

``imaplib`` is synchronous — every network call is wrapped in
``asyncio.to_thread`` so the FastAPI event loop never blocks. One short-lived
connection per operation: simple, no stale-socket handling.
"""

import asyncio
import email
import email.policy
import imaplib
import logging
from dataclasses import dataclass
from email.message import Message
from email.utils import parseaddr

from app.integrations.errors import ExternalIntegrationError

logger = logging.getLogger(__name__)

IMAP_TIMEOUT_SECONDS = 30.0
DEFAULT_FOLDER = "INBOX"


@dataclass(frozen=True)
class RawEmail:
    """Typed boundary model — one fetched mail, headers parsed, body decoded."""

    uid: int
    message_id: str
    from_address: str  # bare address, lowercase (allowlist input)
    subject: str
    body_text: str
    folder: str


def _body_text(msg: Message) -> str:
    """Prefer the text/plain part; fall back to any decodable payload."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        for part in msg.walk():
            if part.get_content_maintype() == "text":
                payload = part.get_payload(decode=True)
                if payload is not None:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        return str(msg.get_payload())
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def parse_rfc822(raw_bytes: bytes, uid: int, folder: str = DEFAULT_FOLDER) -> RawEmail:
    """Parse one RFC822 message into ``RawEmail`` (also used by fixture tests)."""
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.compat32)
    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        # No Message-ID header → synthesize a stable key from UID+folder so
        # dedup still works (IC§7.4 fallback note).
        message_id = f"<uid-{uid}@{folder}>"
    _, from_address = parseaddr(msg.get("From") or "")
    return RawEmail(
        uid=uid,
        message_id=message_id,
        from_address=from_address.lower(),
        subject=(msg.get("Subject") or "").strip(),
        body_text=_body_text(msg),
        folder=folder,
    )


class IMAPClient:
    """Delegate-mailbox transport: fetch UNSEEN by UID, STORE ``\\Seen`` by UID."""

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        folder: str = DEFAULT_FOLDER,
    ) -> None:
        self._host = host
        self._user = user
        self._password = password
        self.folder = folder

    def _connect(self) -> imaplib.IMAP4_SSL:
        conn = imaplib.IMAP4_SSL(self._host, timeout=IMAP_TIMEOUT_SECONDS)
        conn.login(self._user, self._password)
        conn.select(self.folder)
        return conn

    def _fetch_unseen_sync(self) -> list[RawEmail]:
        conn = self._connect()
        try:
            status, data = conn.uid("SEARCH", None, "UNSEEN")
            if status != "OK":
                raise ExternalIntegrationError(
                    f"IMAP SEARCH UNSEEN failed: {status}", retryable=True
                )
            uids = data[0].split() if data and data[0] else []
            mails: list[RawEmail] = []
            for uid_bytes in uids:
                status, msg_data = conn.uid("FETCH", uid_bytes.decode(), "(BODY.PEEK[])")
                if status != "OK" or not msg_data or msg_data[0] is None:
                    logger.warning("IMAP FETCH uid=%s failed: %s", uid_bytes, status)
                    continue
                raw_bytes = msg_data[0][1]
                mails.append(parse_rfc822(raw_bytes, int(uid_bytes), self.folder))
            return mails
        finally:
            self._logout(conn)

    def _store_seen_sync(self, uid: int) -> None:
        conn = self._connect()
        try:
            status, _ = conn.uid("STORE", str(uid), "+FLAGS", r"(\Seen)")
            if status != "OK":
                raise ExternalIntegrationError(
                    f"IMAP STORE \\Seen uid={uid} failed: {status}", retryable=True
                )
        finally:
            self._logout(conn)

    @staticmethod
    def _logout(conn: imaplib.IMAP4_SSL) -> None:
        try:
            conn.logout()
        except (imaplib.IMAP4.error, OSError):  # best-effort close
            pass

    async def fetch_unseen(self) -> list[RawEmail]:
        try:
            return await asyncio.to_thread(self._fetch_unseen_sync)
        except ExternalIntegrationError:
            raise
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ExternalIntegrationError(f"IMAP fetch failed: {exc}", retryable=True) from exc

    async def store_seen(self, uid: int) -> None:
        try:
            await asyncio.to_thread(self._store_seen_sync, uid)
        except ExternalIntegrationError:
            raise
        except (imaplib.IMAP4.error, OSError) as exc:
            raise ExternalIntegrationError(
                f"IMAP STORE \\Seen failed: {exc}", retryable=True
            ) from exc
