"""Agent A reasoning orchestration (TASK-08, Spec §6.3b/§6.4, IC§5.2/5.3).

Runs one fresh stateless Agent A chat, then persists only the qualitative text in
``eta_history.note``. This service never assigns ``shipments.eta_current`` — ETA
numbers remain owned by the rule engine.
"""

import asyncio
import logging

from sqlalchemy import select

from app.agents import agent_a
from app.config import settings
from app.db.base import async_session_factory
from app.db.models import EtaHistory, Shipment
from app.integrations.errors import ExternalIntegrationError

logger = logging.getLogger(__name__)


async def run_agent_a(shipment_id: int) -> str:
    """Run Agent A for one shipment and persist its assessment as a history note."""
    runner = agent_a.build_agent_a()
    assessment = await runner.run(agent_a.analysis_message(shipment_id))
    if not assessment:
        raise ExternalIntegrationError("Agent A trả nhận định rỗng", retryable=True)

    async with async_session_factory() as session:
        shipment = await session.get(Shipment, shipment_id)
        if shipment is None:
            raise ValueError(f"shipment {shipment_id} not found")
        if shipment.eta_current is None:
            raise ValueError(f"shipment {shipment_id} chưa có eta_current")

        last_row = (
            await session.execute(
                select(EtaHistory)
                .where(EtaHistory.shipment_id == shipment_id)
                .order_by(EtaHistory.recorded_at.desc(), EtaHistory.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if last_row is not None and last_row.eta_value == shipment.eta_current:
            last_row.note = assessment
        else:
            session.add(
                EtaHistory(
                    shipment_id=shipment_id,
                    eta_value=shipment.eta_current,
                    source="weather_adjusted",
                    note=assessment,
                )
            )
        await session.commit()
    return assessment


async def _run_scheduled_once() -> int:
    """Run Agent A once for every on-sea shipment; isolate per-shipment failures."""
    async with async_session_factory() as session:
        shipment_ids = list(
            (
                await session.execute(
                    select(Shipment.id)
                    .where(Shipment.status == "on_sea")
                    .order_by(Shipment.id)
                )
            ).scalars()
        )

    completed = 0
    for shipment_id in shipment_ids:
        try:
            await run_agent_a(shipment_id)
        except ExternalIntegrationError as exc:
            if not exc.retryable:
                logger.warning("reasoning scheduler disabled: %s", exc)
                break
            logger.warning("Agent A shipment %d failed: %s", shipment_id, exc)
        except Exception:  # noqa: BLE001 — one bad shipment must not stop scheduler
            logger.exception("Agent A shipment %d failed", shipment_id)
        else:
            completed += 1
    return completed


async def run_scheduler() -> None:
    """IC§5.3: scheduled twice daily (RESEARCH_CADENCE_HOURS, default 12)."""
    interval_s = settings.RESEARCH_CADENCE_HOURS * 3600
    while True:
        try:
            completed = await _run_scheduled_once()
            if completed:
                logger.info("Agent A scheduled analysis: completed %d shipment(s)", completed)
        except Exception:  # noqa: BLE001 — background job must survive one bad cycle
            logger.exception("Agent A scheduler cycle failed")
        await asyncio.sleep(interval_s)


async def run_agent_a_background(shipment_id: int) -> None:
    """Manual-trigger task wrapper: log failures without crashing the app."""
    try:
        await run_agent_a(shipment_id)
    except Exception:  # noqa: BLE001 — detached task must consume its exception
        logger.exception("manual Agent A analysis failed for shipment %d", shipment_id)
