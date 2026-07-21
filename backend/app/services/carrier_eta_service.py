"""Carrier ETA service (§6.7b/§6.7c) — best-effort baseline, never blocks tracking.

One attempt per call: run the agentic browser session, parse the ETA marker,
write ``shipments.eta_original`` + ``eta_original_source='carrier_scrape'`` +
one ``eta_history(source='original')`` row in a single transaction — only when
``eta_original`` is still empty. ``eta_current`` is NEVER touched here.

Every failure mode (LLM error, MCP down, captcha, login wall, parse fail) is a
normal operational event: log + return. Nothing raises past this module —
manual entry (PATCH ``eta_original`` → source ``manual``) stays the parallel
primary path, and AIS tracking is never affected (acceptance v0.9.12).
"""

import logging
import re
import time
from datetime import datetime, timezone

from app.agents import carrier_eta_agent
from app.db.base import async_session_factory
from app.db.models import EtaHistory, Shipment

logger = logging.getLogger(__name__)

_ETA_FOUND_RE = re.compile(r"^ETA_FOUND:\s*(?P<value>\S.*)$", re.MULTILINE)
_ETA_NOT_FOUND_RE = re.compile(r"^ETA_NOT_FOUND:\s*(?P<reason>.*)$", re.MULTILINE)


def parse_agent_eta(text: str) -> datetime | None:
    """Extract the ETA from the agent's marker; tz-aware UTC or None (IC§15)."""
    match = _ETA_FOUND_RE.search(text or "")
    if match is None:
        return None
    raw = match.group("value").strip().rstrip(".")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        # Hãng công bố giờ địa phương không kèm offset — coi là UTC (best-effort baseline).
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _failure_reason(text: str) -> str:
    match = _ETA_NOT_FOUND_RE.search(text or "")
    if match is not None:
        return match.group("reason").strip() or "unknown"
    return "parse-fail"


async def fetch_carrier_eta(shipment_id: int) -> None:
    """One best-effort carrier ETA fetch. Never raises (non-blocking guarantee)."""
    started = time.monotonic()
    outcome = "error"
    carrier = ""
    try:
        async with async_session_factory() as session:
            shipment = await session.get(Shipment, shipment_id)
            if shipment is None:
                outcome = "shipment-missing"
                return
            if shipment.eta_original is not None:
                outcome = "already-set"
                return
            carrier = shipment.carrier
            bl_number = shipment.bl_number
            container_no = shipment.container_no
            pod = shipment.pod

        text = await carrier_eta_agent.run_carrier_eta_agent(
            carrier=carrier,
            bl_number=bl_number,
            container_no=container_no,
            pod=pod,
        )
        eta = parse_agent_eta(text)
        if eta is None:
            outcome = _failure_reason(text)
            return

        async with async_session_factory() as session:
            async with session.begin():
                shipment = await session.get(Shipment, shipment_id)
                if shipment is None:
                    outcome = "shipment-missing"
                    return
                if shipment.eta_original is not None:
                    # User đã nhập tay trong lúc agent chạy — nhập tay thắng.
                    outcome = "already-set"
                    return
                shipment.eta_original = eta
                shipment.eta_original_source = "carrier_scrape"
                session.add(
                    EtaHistory(
                        shipment_id=shipment_id,
                        eta_value=eta,
                        source="original",
                        note=f"Carrier ETA agent ({carrier})",
                    )
                )
        outcome = "ok"
    except Exception as exc:  # noqa: BLE001 — non-blocking là acceptance criterion
        outcome = f"error: {exc!r}"[:300]
        logger.warning(
            "carrier ETA fetch shipment %s failed (fallback nhập tay): %s",
            shipment_id,
            outcome,
        )
    finally:
        logger.info(
            "carrier ETA fetch shipment=%s carrier=%r outcome=%s duration=%.1fs",
            shipment_id,
            carrier,
            outcome,
            time.monotonic() - started,
        )
