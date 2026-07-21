"""Research findings REST router (IC§3.2) — TASK-09."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import ResearchFindingOut
from app.api.deps import get_current_user, get_session
from app.api.errors import raise_api_error
from app.db.models import ResearchFinding, User
from app.services.research_service import finding_to_out

router = APIRouter(prefix="/api/v1/research-findings", tags=["research"])


@router.get("", dependencies=[Depends(get_current_user)])
async def list_research_findings(
    shipment_id: int | None = Query(None),
    route_key: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[ResearchFindingOut]:
    query = select(ResearchFinding).order_by(
        ResearchFinding.created_at.desc(), ResearchFinding.id.desc()
    )
    if shipment_id is not None:
        query = query.where(ResearchFinding.shipment_id == shipment_id)
    if route_key is not None:
        query = query.where(ResearchFinding.route_key == route_key)
    rows = (await session.execute(query)).scalars().all()
    return [finding_to_out(row) for row in rows]


@router.post("/{finding_id}/verify")
async def verify_research_finding(
    finding_id: int,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(get_current_user),
) -> ResearchFindingOut:
    finding = await session.get(ResearchFinding, finding_id)
    if finding is None:
        raise_api_error(404, "FINDING_NOT_FOUND", f"Không tìm thấy finding #{finding_id}")
    finding.verified = True
    finding.verified_by = user.id if user is not None else None
    await session.commit()
    return finding_to_out(finding)
