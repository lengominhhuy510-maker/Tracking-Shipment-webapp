"""Shipments REST router (IC§3.2)."""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_session
from app.api.errors import raise_api_error
from app.core.monitoring_mode import UnsupportedCombination, derive_monitoring_mode
from app.core.normalize import normalize_container_no, normalize_vessel_name
from app.db.base import async_session_factory
from app.db.models import EtaHistory, Shipment, ShipmentLeg, VesselRegistry, VesselTrail
from app.integrations.errors import ExternalIntegrationError
from app.integrations.llm_client import build_llm_client
from app.services import reasoning_service
from app.schemas.shipment import (
    EtaHistoryOut,
    ResolveManualIn,
    ShipmentCreate,
    ShipmentDetail,
    ShipmentListItem,
    ShipmentPatch,
    TrailPoint,
)
from app.services import carrier_eta_service, scrape_client
from app.services.leg_service import mark_leg_manual, resolve_leg

router = APIRouter(
    prefix="/api/v1/shipments",
    tags=["shipments"],
    dependencies=[Depends(get_current_user)],
)

logger = logging.getLogger(__name__)

_STATUS_ORDER = {"new": 0, "on_sea": 1, "arrived": 2, "delivered": 3}

# PATCH whitelist per IC§3.2; anything else → 400 IMMUTABLE_FIELD
_PATCH_ALLOWED = {"eta_original", "atd", "pol", "pod", "status", "bl_number", "carrier"}


async def _get_shipment_or_404(session: AsyncSession, shipment_id: int) -> Shipment:
    result = await session.execute(
        select(Shipment)
        .where(Shipment.id == shipment_id)
        .options(selectinload(Shipment.legs), selectinload(Shipment.env_conditions))
    )
    shipment = result.scalar_one_or_none()
    if shipment is None:
        raise_api_error(404, "SHIPMENT_NOT_FOUND", f"Không tìm thấy lô #{shipment_id}")
    return shipment


async def _recent_eta_history(
    session: AsyncSession, shipment_id: int, limit: int = 5
) -> list[EtaHistory]:
    result = await session.execute(
        select(EtaHistory)
        .where(EtaHistory.shipment_id == shipment_id)
        .order_by(EtaHistory.recorded_at.desc(), EtaHistory.id.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def _detail(session: AsyncSession, shipment: Shipment) -> ShipmentDetail:
    detail = ShipmentDetail.model_validate(shipment)
    detail.recent_eta_history = [
        EtaHistoryOut.model_validate(row)
        for row in await _recent_eta_history(session, shipment.id)
    ]
    return detail


def _active_leg(shipment: Shipment) -> ShipmentLeg | None:
    return next((leg for leg in shipment.legs if leg.is_active_leg), None)


async def _cached_registry_identity(
    session: AsyncSession, vessel_name: str
) -> tuple[str, str | None] | None:
    """Cache hit (Spec §6.7a) chỉ khi tên chuẩn hoá khớp đúng 1 IMO duy nhất."""
    result = await session.execute(
        select(VesselRegistry)
        .where(VesselRegistry.vessel_name == vessel_name)
        .order_by(VesselRegistry.resolved_at.desc(), VesselRegistry.id.desc())
    )
    rows = result.scalars().all()
    if not rows or len({row.imo for row in rows}) != 1:
        return None
    return rows[0].imo, rows[0].mmsi


# Giữ reference để task nền không bị GC trước khi chạy xong.
_onboarding_tasks: set[asyncio.Task] = set()


def _spawn_onboarding_task(coro, name: str) -> None:
    task = asyncio.create_task(coro, name=name)
    _onboarding_tasks.add(task)
    task.add_done_callback(_onboarding_tasks.discard)


def _spawn_carrier_eta_fetch(shipment_id: int) -> None:
    """§6.7b: sau IMO resolve, lấy carrier ETA nền — tiện ích thêm, fail không sao.

    ``fetch_carrier_eta`` tự kiểm tra ``eta_original`` còn trống và nuốt mọi lỗi
    (acceptance v0.9.12 — không bao giờ chặn tracking/onboarding).
    """
    _spawn_onboarding_task(
        carrier_eta_service.fetch_carrier_eta(shipment_id),
        name=f"carrier-eta-{shipment_id}",
    )


async def _finish_onboarding(
    leg_id: int, cache_name: str, result: scrape_client.IMOResolverResult | scrape_client.ScrapeError
) -> None:
    async with async_session_factory() as session:
        if isinstance(result, scrape_client.ScrapeError):
            await mark_leg_manual(session, leg_id, result.error_code)
            return
        # Cache registry trước (transaction riêng — resolve_leg tự mở session.begin()).
        # Key = tên đã normalize từ request (IC§9) — tên VesselFinder trả về có thể
        # kèm loại tàu ("EVER GIVEN CONTAINER SHIP") nên không dùng làm cache key.
        async with session.begin():
            session.add(
                VesselRegistry(
                    vessel_name=cache_name,
                    imo=result.imo,
                    mmsi=result.mmsi,
                    resolved_via="vesselfinder",
                )
            )
        await resolve_leg(session, leg_id, result.imo, result.mmsi, "deterministic_scrape")
        leg = await session.get(ShipmentLeg, leg_id)
        if leg is not None:
            _spawn_carrier_eta_fetch(leg.shipment_id)


async def _run_onboarding_scrape(
    leg_id: int, vessel_name: str, voyage_no: str | None, pol: str | None, pod: str | None
) -> None:
    """Task nền (không block response): scrape → resolve_leg | mark_leg_manual (Spec §6.7a)."""
    try:
        result = await scrape_client.resolve_imo(vessel_name, voyage_no, pol, pod)
        await _finish_onboarding(leg_id, vessel_name, result)
    except Exception:
        logger.exception("onboarding scrape cho leg %s thất bại ngoài luồng error_code", leg_id)


async def _run_onboarding_poll(leg_id: int, vessel_name: str, job_id: str) -> None:
    """Task nền cho retry: job đã enqueue inline (trả job_id thật), chỉ còn poll."""
    try:
        result = await scrape_client.poll_imo_job(job_id)
        await _finish_onboarding(leg_id, vessel_name, result)
    except Exception:
        logger.exception("onboarding poll job %s cho leg %s thất bại", job_id, leg_id)


@router.post("/", status_code=201, response_model=ShipmentDetail)
async def create_shipment(
    payload: ShipmentCreate, session: AsyncSession = Depends(get_session)
) -> ShipmentDetail:
    try:
        container_no = normalize_container_no(payload.container_no)
    except ValueError as exc:
        raise_api_error(400, "INVALID_CONTAINER_NO", str(exc))

    try:
        monitoring_mode = derive_monitoring_mode(payload.shipment_direction, payload.incoterm)
    except UnsupportedCombination as exc:
        raise_api_error(400, "UNSUPPORTED_INCOTERM_COMBINATION", str(exc))

    vessel_name = normalize_vessel_name(payload.vessel_name)

    shipment = Shipment(
        bl_number=payload.bl_number,
        container_no=container_no,
        incoterm=payload.incoterm,
        shipment_direction=payload.shipment_direction,
        carrier=payload.carrier,
        vessel_name=vessel_name,
        voyage_no=payload.voyage_no,
        pol=payload.pol,
        pod=payload.pod,
        eta_original=payload.eta_original,
        eta_original_source="manual" if payload.eta_original is not None else None,
        eta_current=payload.eta_original,
        monitoring_mode=monitoring_mode,
    )
    session.add(shipment)
    await session.flush()

    leg = ShipmentLeg(
        shipment_id=shipment.id,
        leg_no=1,
        vessel_name=vessel_name,
        voyage_no=payload.voyage_no,
        pol=payload.pol,
        pod=payload.pod,
        is_active_leg=True,
    )
    session.add(leg)
    await session.flush()
    leg_id = leg.id
    shipment_id = shipment.id
    await session.commit()

    if payload.imo and payload.mmsi:
        await resolve_leg(session, leg_id, payload.imo, payload.mmsi, "manual")
        _spawn_carrier_eta_fetch(shipment_id)
    else:
        cached = await _cached_registry_identity(session, vessel_name)
        # Kết thúc transaction đọc (autobegin) — resolve_leg tự mở session.begin().
        await session.rollback()
        if cached is not None:
            imo, mmsi = cached
            await resolve_leg(session, leg_id, imo, mmsi, "cache_hit")
            _spawn_carrier_eta_fetch(shipment_id)
        else:
            _spawn_onboarding_task(
                _run_onboarding_scrape(
                    leg_id, vessel_name, payload.voyage_no, payload.pol, payload.pod
                ),
                name=f"onboard-{leg_id}",
            )

    shipment = await _get_shipment_or_404(session, shipment_id)
    return await _detail(session, shipment)


@router.get("/", response_model=list[ShipmentListItem])
async def list_shipments(
    status: str | None = Query(None),
    direction: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[ShipmentListItem]:
    stmt = select(Shipment).order_by(Shipment.id)
    if status is not None:
        stmt = stmt.where(Shipment.status == status)
    if direction is not None:
        stmt = stmt.where(Shipment.shipment_direction == direction)
    result = await session.execute(stmt)
    return [ShipmentListItem.model_validate(s) for s in result.scalars().all()]


@router.post("/{shipment_id}/analyze", status_code=202)
async def analyze_shipment(
    shipment_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Queue one manual Agent A run (IC§3.2/§5.3 — "Phân tích ngay")."""
    await _get_shipment_or_404(session, shipment_id)
    try:
        build_llm_client()  # fail clearly before accepting a job that cannot run
    except ExternalIntegrationError as exc:
        raise_api_error(503, "LLM_NOT_CONFIGURED", str(exc))
    background_tasks.add_task(reasoning_service.run_agent_a_background, shipment_id)
    return {"status": "queued"}


@router.get("/{shipment_id}", response_model=ShipmentDetail)
async def get_shipment(
    shipment_id: int, session: AsyncSession = Depends(get_session)
) -> ShipmentDetail:
    shipment = await _get_shipment_or_404(session, shipment_id)
    return await _detail(session, shipment)


@router.get("/{shipment_id}/trail", response_model=list[TrailPoint])
async def get_trail(
    shipment_id: int, session: AsyncSession = Depends(get_session)
) -> list[TrailPoint]:
    await _get_shipment_or_404(session, shipment_id)
    result = await session.execute(
        select(VesselTrail)
        .where(VesselTrail.shipment_id == shipment_id)
        .order_by(VesselTrail.recorded_at.desc(), VesselTrail.id.desc())
        .limit(12)
    )
    return [TrailPoint.model_validate(p) for p in reversed(result.scalars().all())]


@router.get("/{shipment_id}/eta-history", response_model=list[EtaHistoryOut])
async def get_eta_history(
    shipment_id: int, session: AsyncSession = Depends(get_session)
) -> list[EtaHistoryOut]:
    await _get_shipment_or_404(session, shipment_id)
    result = await session.execute(
        select(EtaHistory)
        .where(EtaHistory.shipment_id == shipment_id)
        .order_by(EtaHistory.recorded_at, EtaHistory.id)
    )
    return [EtaHistoryOut.model_validate(row) for row in result.scalars().all()]


@router.patch("/{shipment_id}", response_model=ShipmentDetail)
async def patch_shipment(
    shipment_id: int, payload: ShipmentPatch, session: AsyncSession = Depends(get_session)
) -> ShipmentDetail:
    extras = set((payload.model_extra or {}).keys())
    if extras:
        raise_api_error(
            400,
            "IMMUTABLE_FIELD",
            f"Field không được phép sửa qua PATCH: {', '.join(sorted(extras))}",
        )

    shipment = await _get_shipment_or_404(session, shipment_id)
    fields = payload.model_dump(exclude_unset=True)

    if ("pol" in fields or "pod" in fields) and shipment.atd is not None:
        raise_api_error(400, "IMMUTABLE_FIELD", "pol/pod chỉ sửa được khi chưa có ATD")

    if "status" in fields:
        new_status = fields["status"]
        allowed_backward = _STATUS_ORDER[new_status] < _STATUS_ORDER[shipment.status]
        if new_status not in ("arrived", "delivered") and not allowed_backward:
            raise_api_error(
                400,
                "IMMUTABLE_FIELD",
                "status chỉ nhận arrived/delivered hoặc quay lui (IC§0.3)",
            )

    for key, value in fields.items():
        setattr(shipment, key, value)

    if "eta_original" in fields:
        shipment.eta_original_source = "manual"
    if "atd" in fields and fields["atd"] is not None and shipment.status == "new":
        shipment.status = "on_sea"  # IC§0.3: nhập ATD tự flip new→on_sea
    if fields.get("status") == "delivered":
        shipment.delivered_at = datetime.now(timezone.utc)

    await session.commit()
    shipment = await _get_shipment_or_404(session, shipment_id)
    return await _detail(session, shipment)


@router.post("/{shipment_id}/resolve-manual", response_model=ShipmentDetail)
async def resolve_manual(
    shipment_id: int, payload: ResolveManualIn, session: AsyncSession = Depends(get_session)
) -> ShipmentDetail:
    shipment = await _get_shipment_or_404(session, shipment_id)
    leg = _active_leg(shipment)
    if leg is None:
        raise_api_error(404, "SHIPMENT_NOT_FOUND", f"Lô #{shipment_id} không có leg active")
    leg_id = leg.id
    # Kết thúc transaction đọc (autobegin) — resolve_leg tự mở session.begin() (IC§3.2).
    await session.rollback()
    await resolve_leg(session, leg_id, payload.imo, payload.mmsi, "manual")
    _spawn_carrier_eta_fetch(shipment_id)
    shipment = await _get_shipment_or_404(session, shipment_id)
    return await _detail(session, shipment)


@router.post("/{shipment_id}/retry-onboarding", status_code=202)
async def retry_onboarding(
    shipment_id: int, session: AsyncSession = Depends(get_session)
) -> dict:
    shipment = await _get_shipment_or_404(session, shipment_id)
    leg = _active_leg(shipment)
    if leg is None or leg.onboarding_status != "manual_required":
        raise_api_error(
            400, "ONBOARDING_NOT_RETRYABLE", "Leg active không ở trạng thái manual_required"
        )
    leg.onboarding_status = "pending"
    leg.onboarding_error = None
    shipment.onboarding_status = "pending"
    shipment.onboarding_error = None
    leg_id, vessel_name, voyage_no, pol, pod = (
        leg.id,
        leg.vessel_name,
        leg.voyage_no,
        leg.pol,
        leg.pod,
    )
    await session.commit()

    # Enqueue inline để trả job_id THẬT của /scrape-jobs (IC§3.3); poll ở task nền.
    job_id = await scrape_client.enqueue_imo(vessel_name, voyage_no, pol, pod)
    if isinstance(job_id, scrape_client.ScrapeError):
        # Gate không enqueue được → fallback job_ref cục bộ, task nền tự retry
        # trọn gói (enqueue+poll) và mark manual nếu vẫn lỗi.
        job_ref = f"onboard-{leg_id}-{uuid4().hex[:8]}"
        _spawn_onboarding_task(
            _run_onboarding_scrape(leg_id, vessel_name, voyage_no, pol, pod), name=job_ref
        )
        return {"leg_id": leg_id, "job_id": job_ref}

    _spawn_onboarding_task(
        _run_onboarding_poll(leg_id, vessel_name, job_id), name=f"onboard-poll-{job_id}"
    )
    return {"leg_id": leg_id, "job_id": job_id}
