"""Agent proposals REST router (IC§3.2) — list, approve, reject."""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_session
from app.api.errors import raise_api_error
from app.db.base import async_session_factory
from app.db.models import AgentProposal, User
from app.services import proposal_service

router = APIRouter(
    prefix="/api/v1/agent-proposals",
    tags=["agent-proposals"],
    dependencies=[Depends(get_current_user)],
)

logger = logging.getLogger(__name__)


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int | None
    source_email_id: str
    extracted_json: dict | None
    proposed_action: str | None
    status: str
    decided_by: int | None
    created_at: object
    decided_at: object


class RejectIn(BaseModel):
    reason: str | None = None


@router.get("", response_model=list[ProposalOut])
async def list_proposals(
    status: str = Query("pending"),
    session: AsyncSession = Depends(get_session),
) -> list[AgentProposal]:
    rows = await session.execute(
        select(AgentProposal)
        .where(AgentProposal.status == status)
        .order_by(AgentProposal.created_at.desc(), AgentProposal.id.desc())
    )
    return list(rows.scalars())


async def _run_rollover_bg(job: proposal_service.RolloverJob) -> None:
    try:
        async with async_session_factory() as session:
            await proposal_service.run_rollover(job, session)
    except Exception:  # noqa: BLE001 — background task must not crash the app
        logger.exception("rollover job for leg %d failed", job.new_leg_id)


@router.post("/{proposal_id}/approve", response_model=ProposalOut)
async def approve_proposal(
    proposal_id: int,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentProposal:
    try:
        proposal, rollover = await proposal_service.approve(session, proposal_id, user.id)
    except proposal_service.ProposalNotFound:
        raise_api_error(404, "PROPOSAL_NOT_FOUND", f"Không tìm thấy proposal #{proposal_id}")
    except proposal_service.ProposalAlreadyDecided:
        raise_api_error(
            409, "PROPOSAL_ALREADY_DECIDED", f"Proposal #{proposal_id} đã được quyết định"
        )
    if rollover is not None:
        background.add_task(_run_rollover_bg, rollover)
    return proposal


@router.post("/{proposal_id}/reject", response_model=ProposalOut)
async def reject_proposal(
    proposal_id: int,
    payload: RejectIn | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentProposal:
    try:
        return await proposal_service.reject(
            session, proposal_id, user.id, payload.reason if payload else None
        )
    except proposal_service.ProposalNotFound:
        raise_api_error(404, "PROPOSAL_NOT_FOUND", f"Không tìm thấy proposal #{proposal_id}")
    except proposal_service.ProposalAlreadyDecided:
        raise_api_error(
            409, "PROPOSAL_ALREADY_DECIDED", f"Proposal #{proposal_id} đã được quyết định"
        )
