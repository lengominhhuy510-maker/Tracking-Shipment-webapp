"""Proposal decision service (§7.1 approve/reject, §6.8d rollover chain).

``approve`` is the ONLY path from an email proposal to real data changes and it
requires a human decision (``decided_by``) — §7.2. In one transaction it marks
the proposal approved, applies ``new_eta`` to ``eta_current`` +
``eta_history(source='email_agent')``, and for a rollover inserts the new
``shipment_legs`` row (SAME ``leg_no``, old row ``superseded_at``). The IMO
scrape of the new vessel runs AFTER commit (IC§3.2: proposal flips approved
immediately, the new leg stays ``pending`` until the resolver finishes) via
``run_rollover`` — success → ``resolve_and_activate_leg`` (active flips, mirror
to shipments, ResubscribeSignal); failure → ``mark_leg_manual``.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.email_agent import EmailExtraction
from app.core.normalize import normalize_vessel_name
from app.db.models import AgentProposal, EtaHistory, Shipment, ShipmentLeg
from app.services import scrape_client
from app.services.leg_service import mark_leg_manual, resolve_and_activate_leg

logger = logging.getLogger(__name__)


class ProposalNotFound(Exception):
    pass


class ProposalAlreadyDecided(Exception):
    pass


@dataclass(frozen=True)
class RolloverJob:
    """Post-commit work: scrape the new vessel then activate the new leg."""

    new_leg_id: int
    vessel_name: str
    voyage_no: str | None
    pol: str
    pod: str


async def _get_pending(session: AsyncSession, proposal_id: int) -> AgentProposal:
    proposal = await session.get(AgentProposal, proposal_id)
    if proposal is None:
        raise ProposalNotFound(f"proposal {proposal_id} not found")
    if proposal.status != "pending":
        raise ProposalAlreadyDecided(f"proposal {proposal_id} đã {proposal.status}")
    return proposal


async def approve(
    session: AsyncSession,
    proposal_id: int,
    user_id: int,
) -> tuple[AgentProposal, RolloverJob | None]:
    """Approve one pending proposal; returns the rollover job to run post-commit.

    Mutate trên transaction hiện có rồi ``session.commit()`` (pattern như
    shipments ``patch_shipment``). KHÔNG dùng ``session.begin()``: session từ
    request đã autobegin sẵn (``get_current_user`` đọc User) → ``begin()`` sẽ báo
    "A transaction is already begun on this Session".
    """
    rollover: RolloverJob | None = None
    proposal = await _get_pending(session, proposal_id)
    proposal.status = "approved"
    proposal.decided_by = user_id
    proposal.decided_at = datetime.now(UTC)

    extraction = (
        EmailExtraction.model_validate(proposal.extracted_json)
        if proposal.extracted_json
        else None
    )
    shipment = (
        await session.get(Shipment, proposal.shipment_id)
        if proposal.shipment_id is not None
        else None
    )

    if extraction is not None and shipment is not None:
        if extraction.new_eta is not None:
            shipment.eta_current = extraction.new_eta
            session.add(
                EtaHistory(
                    shipment_id=shipment.id,
                    eta_value=extraction.new_eta,
                    source="email_agent",
                    note=f"Proposal #{proposal.id} approved",
                )
            )

        if extraction.new_vessel_name:
            active_leg = (
                await session.execute(
                    select(ShipmentLeg)
                    .where(ShipmentLeg.shipment_id == shipment.id)
                    .where(ShipmentLeg.is_active_leg)
                )
            ).scalar_one_or_none()
            if active_leg is None:
                raise RuntimeError(f"shipment {shipment.id} không có active leg")
            new_vessel = normalize_vessel_name(extraction.new_vessel_name)
            active_leg.superseded_at = datetime.now(UTC)
            new_leg = ShipmentLeg(
                shipment_id=shipment.id,
                leg_no=active_leg.leg_no,
                vessel_name=new_vessel,
                voyage_no=extraction.to_voyage,
                pol=active_leg.pol,
                pod=active_leg.pod,
                onboarding_status="pending",
                is_active_leg=False,
            )
            session.add(new_leg)
            await session.flush()
            rollover = RolloverJob(
                new_leg_id=new_leg.id,
                vessel_name=new_vessel,
                voyage_no=extraction.to_voyage,
                pol=active_leg.pol,
                pod=active_leg.pod,
            )
    await session.commit()
    return proposal, rollover


async def reject(
    session: AsyncSession,
    proposal_id: int,
    user_id: int,
    reason: str | None = None,
) -> AgentProposal:
    # Mutate trên transaction hiện có rồi commit (pattern patch_shipment) — session
    # từ request đã autobegin nên session.begin() sẽ báo "already begun".
    proposal = await _get_pending(session, proposal_id)
    proposal.status = "rejected"
    proposal.decided_by = user_id
    proposal.decided_at = datetime.now(UTC)
    await session.commit()
    if reason:
        logger.info("proposal %d rejected bởi user %d: %s", proposal_id, user_id, reason)
    return proposal


async def run_rollover(
    job: RolloverJob,
    session: AsyncSession,
    *,
    resolve_imo=scrape_client.resolve_imo,
    activate=resolve_and_activate_leg,
    mark_manual=mark_leg_manual,
) -> None:
    """Resolve the new vessel's IMO then flip the leg active (§6.8d step 1+3)."""
    result = await resolve_imo(
        job.vessel_name, job.voyage_no, job.pol, job.pod
    )
    if isinstance(result, scrape_client.ScrapeError):
        logger.warning(
            "rollover leg %d: IMO resolve failed (%s) → manual_required",
            job.new_leg_id,
            result.error_code,
        )
        await mark_manual(session, job.new_leg_id, result.error_code)
        return
    await activate(
        session, job.new_leg_id, result.imo, result.mmsi, "deterministic_scrape"
    )
