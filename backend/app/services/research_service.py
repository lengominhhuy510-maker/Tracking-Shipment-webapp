"""Agent A↔B research orchestration (TASK-09, Spec §6.3c/d, IC§5.2).

Cache check (route_key, TTL = RESEARCH_CADENCE_HOURS) runs BEFORE any Agent B
call; the wrapper — never the LLM — persists findings and enforces the hard cap
of 3 Agent B runs (defense-in-depth on top of AG2 ``max_turns=3``).
"""

import logging
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import select

from app.agents import agent_b
from app.agents.schemas import ResearchFindingOut
from app.agents.tools import _route_key
from app.config import settings
from app.db.base import async_session_factory
from app.db.models import ResearchFinding, Shipment
from app.integrations.errors import ExternalIntegrationError

logger = logging.getLogger(__name__)

_HARD_CAP = 3
# key -> (attempt count, window start); window length = RESEARCH_CADENCE_HOURS
_attempts: dict[str, tuple[int, datetime]] = {}

_RETRY_SUFFIX = (
    "\n\nLần trước bạn trả sai format. Trả lại CHỈ MỘT object JSON hợp lệ đúng "
    "schema {event, relevance, route_impact, confidence, sources} — không văn xuôi."
)


def reset_hard_cap() -> None:
    _attempts.clear()


def _under_cap(key: str) -> bool:
    now = datetime.now(UTC)
    count, started = _attempts.get(key, (0, now))
    if now - started > timedelta(hours=settings.RESEARCH_CADENCE_HOURS):
        count, started = 0, now
    if count >= _HARD_CAP:
        return False
    _attempts[key] = (count + 1, started)
    return True


def _empty_finding(reason: str) -> ResearchFindingOut:
    """IC§5.2 degraded result — never crashes the A-loop, never persisted."""
    return ResearchFindingOut(
        event=f"research không khả dụng: {reason}",
        relevance="thap",
        route_impact="chưa xác định — cần xác minh",
        confidence="thap",
        sources=["https://example.invalid/research-unavailable"],
    )


def finding_to_out(row: ResearchFinding) -> ResearchFindingOut:
    return ResearchFindingOut(
        event=row.event,
        relevance=row.relevance,
        route_impact=row.route_impact or "",
        confidence=row.confidence,
        sources=[str(url) for url in (row.sources or [])],
    )


def _parse_finding(raw: str) -> ResearchFindingOut | None:
    text = raw.strip()
    candidates = [text]
    if "{" in text and "}" in text:
        candidates.append(text[text.find("{") : text.rfind("}") + 1])
    for candidate in candidates:
        try:
            return ResearchFindingOut.model_validate_json(candidate)
        except ValidationError:
            continue
    return None


async def _cached_finding(route_key: str | None) -> ResearchFindingOut | None:
    """§6.3d: newest finding on the same route within TTL — shared across shipments."""
    if route_key is None:
        return None
    cutoff = datetime.now(UTC) - timedelta(hours=settings.RESEARCH_CADENCE_HOURS)
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(ResearchFinding)
                .where(
                    ResearchFinding.route_key == route_key,
                    ResearchFinding.created_at > cutoff,
                )
                .order_by(ResearchFinding.created_at.desc(), ResearchFinding.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None or not row.sources:
        return None
    return finding_to_out(row)


async def _persist(shipment_id: int, route_key: str | None, finding: ResearchFindingOut) -> None:
    async with async_session_factory() as session:
        session.add(
            ResearchFinding(
                shipment_id=shipment_id,
                route_key=route_key,
                event=finding.event,
                relevance=finding.relevance,
                route_impact=finding.route_impact,
                confidence=finding.confidence,
                sources=[str(url) for url in finding.sources],
                verified=False,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def request_research(shipment_id: int, focus: str | None = None) -> ResearchFindingOut:
    """Cache-first A↔B research run for one shipment (IC§5.1 tool contract)."""
    async with async_session_factory() as session:
        shipment = await session.get(Shipment, shipment_id)
        if shipment is None:
            raise ValueError(f"shipment {shipment_id} not found")
        pol, pod, eta_current = shipment.pol, shipment.pod, shipment.eta_current

    route_key = _route_key(pol, pod)
    cached = await _cached_finding(route_key)
    if cached is not None:
        logger.info("research cache hit (route=%s) — không gọi Agent B", route_key)
        return cached

    cap_key = route_key or f"shipment:{shipment_id}"
    if not _under_cap(cap_key):
        logger.warning("research hard cap %d reached (key=%s)", _HARD_CAP, cap_key)
        return _empty_finding(f"vượt hard cap {_HARD_CAP} lần chạy Agent B trong cửa sổ")

    try:
        runner = agent_b.build_agent_b()
    except ExternalIntegrationError as exc:
        logger.warning("Agent B không khả dụng: %s", exc)
        return _empty_finding(str(exc))

    message = agent_b.research_message(
        pol=pol,
        pod=pod,
        route_key=route_key,
        eta_current=eta_current.isoformat() if eta_current is not None else None,
        focus=focus,
    )
    try:
        finding = _parse_finding(await runner.run(message))
        if finding is None:  # sai format → retry đúng 1 lần (§6.3c)
            finding = _parse_finding(await runner.run(message + _RETRY_SUFFIX))
    except ExternalIntegrationError as exc:
        logger.warning("Agent B chat failed: %s", exc)
        return _empty_finding(str(exc))

    if finding is None:
        logger.warning("Agent B trả sai format sau 1 retry (shipment=%d)", shipment_id)
        return _empty_finding("Agent B trả sai format sau 1 retry")

    await _persist(shipment_id, route_key, finding)
    return finding
