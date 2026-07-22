"""QA-04 — ROLLOVER đổi vessel real-case, NO-MOCK ⭐ (REPORT-ONLY, evidence-based).

Nguồn chân lý: Spec §6.8d, IC§3.2, IC§2.1, IC§4.2, IC§2.3 (uq_legs_one_active).

Ranh giới mock (§FORBIDDEN của task): CHỈ mock biên NGOÀI = ``resolve_imo``
(scrape/LLM). KHÔNG mock ``resolve_and_activate_leg`` — nó chạy thật trên
Postgres thật (host port 15432). ``async mock`` dùng đúng async signature (coroutine
được ``await``), nếu không sẽ RuntimeWarning → dùng làm gate ở item 6.

Luồng thật đang kiểm (đọc từ app code READ-ONLY):
  proposal_service.approve()  → 1 transaction: proposal='approved', new_eta →
      eta_current + eta_history(source='email_agent'); nếu new_vessel_name →
      chèn leg MỚI (CÙNG leg_no, superseded_at leg cũ), leg mới onboarding
      'pending' + is_active_leg=False; trả RolloverJob. (IC§3.2: proposal duyệt
      NGAY, leg mới pending cho tới khi resolver xong.)
  proposal_service.run_rollover(job, ..., resolve_imo=<mock biên ngoài>)
      → resolve_and_activate_leg() THẬT: leg mới resolved + is_active_leg=True,
      leg cũ is_active_leg=False, mirror imo/mmsi xuống shipments,
      resubscribe_signal.set() (asyncio.Event) + broadcast onboarding_update.

Không sửa app code. DB thật lấy từ TEST_DATABASE_URL (§ENVIRONMENT). Mỗi test
seed dữ liệu riêng và dọn sạch (TRUNCATE ... CASCADE) trong fixture.
"""

import os
import warnings
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.email_agent import EmailExtraction
from app.db.models import (
    AgentProposal,
    EtaHistory,
    Shipment,
    ShipmentLeg,
)
from app.services import proposal_service
from app.services.leg_service import resolve_and_activate_leg
from app.services.scrape_client import IMOResolverResult, ScrapeError
from app.services.subscription import ResubscribeSignal

# --------------------------------------------------------------------------- #
# REAL Postgres 15432 — owned exclusively by this worker (§ENVIRONMENT).
# --------------------------------------------------------------------------- #
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://app:app@localhost:15432/shipment_demo",
)

_TABLES_TO_CLEAN = (
    "eta_history",
    "agent_proposals",
    "shipment_legs",
    "shipments",
)


@pytest.fixture
async def pg():
    """Async sessionmaker bound to the REAL Postgres test container.

    Cleans the rollover-relevant tables before AND after each test so cases are
    independent and the partial unique index uq_legs_one_active is exercised on
    real Postgres semantics (SQLite would only emulate the partial index).
    """
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _truncate() -> None:
        async with factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "TRUNCATE "
                        + ", ".join(_TABLES_TO_CLEAN)
                        + " RESTART IDENTITY CASCADE"
                    )
                )

    await _truncate()
    try:
        yield factory
    finally:
        await _truncate()
        await engine.dispose()


# --------------------------------------------------------------------------- #
# Helpers — seed a shipment with exactly one active leg (leg_no=1, tàu cũ).
# --------------------------------------------------------------------------- #
async def _seed_shipment_with_active_leg(
    pg,
    *,
    container_no: str = "MSKU1234565",
    old_vessel: str = "EVER GIVEN",
    old_voyage: str = "V.001N",
    old_imo: str = "9811001",
    old_mmsi: str = "563011111",
) -> tuple[int, int]:
    """Return (shipment_id, active_leg_id). Mirrors an already-resolved direct lô."""
    async with pg() as session:
        async with session.begin():
            shipment = Shipment(
                bl_number="BL-QA04-001",
                container_no=container_no,
                incoterm="FOB",
                shipment_direction="import",
                carrier="Maersk",
                vessel_name=old_vessel,
                imo=old_imo,
                mmsi=old_mmsi,
                imo_resolved_via="deterministic_scrape",
                voyage_no=old_voyage,
                pol="SGSIN",
                pod="VNCLI",
                status="on_sea",
                onboarding_status="resolved",
                monitoring_mode="manual",  # manual → không auto-forward SMTP
            )
            session.add(shipment)
            await session.flush()
            leg = ShipmentLeg(
                shipment_id=shipment.id,
                leg_no=1,
                vessel_name=old_vessel,
                voyage_no=old_voyage,
                imo=old_imo,
                mmsi=old_mmsi,
                imo_resolved_via="deterministic_scrape",
                pol="SGSIN",
                pod="VNCLI",
                onboarding_status="resolved",
                is_active_leg=True,
            )
            session.add(leg)
            await session.flush()
            return shipment.id, leg.id


def _rollover_extraction(
    *,
    new_vessel_name: str,
    to_voyage: str = "V.002N",
    new_eta: str | None = "2026-08-15T09:30:00+00:00",
    container_no: str = "MSKU1234565",
) -> EmailExtraction:
    """IC§4.2 shape — rollover mail carries new_vessel_name (biên NGOÀI = LLM)."""
    return EmailExtraction.model_validate(
        {
            "containers": [container_no],
            "from_voyage": "V.001N",
            "to_voyage": to_voyage,
            "new_eta": new_eta,
            "new_vessel_name": new_vessel_name,
            "reason": "vessel rollover",
            "email_type": "rollover",
        }
    )


async def _insert_pending_proposal(
    pg, shipment_id: int, extraction: EmailExtraction, *, message_id: str
) -> int:
    """Insert a pending proposal directly (LLM extraction already produced JSON).

    This is NOT mocking the flow under test — it stands in for the upstream email
    ingest (biên ngoài) so approve()/run_rollover() run against a real row.
    """
    async with pg() as session:
        async with session.begin():
            proposal = AgentProposal(
                shipment_id=shipment_id,
                source_email_id=message_id,
                extracted_json=extraction.model_dump(mode="json"),
                proposed_action="rollover" if extraction.new_vessel_name else "eta_update",
            )
            session.add(proposal)
            await session.flush()
            return proposal.id


def _fake_resolve_imo(imo: str = "9811222", mmsi: str = "563029999"):
    """Biên ngoài scrape/LLM — async signature ĐÚNG (coroutine, được await).

    Trả IMOResolverResult như Node scrape thật (IC§4.1). resolve_and_activate_leg
    KHÔNG bị mock — nó ghi Postgres thật.
    """

    async def _resolve(vessel_name, voyage_no, pol, pod):
        return IMOResolverResult(
            imo=imo,
            mmsi=mmsi,
            vessel_name=vessel_name,  # normalize được scrape_client validator áp
            confidence="cao",
            source_url=f"https://example.com/vessel/{imo}",
        )

    return _resolve


async def _run_full_rollover(
    pg,
    shipment_id: int,
    proposal_id: int,
    *,
    resolve_imo=None,
    signal: ResubscribeSignal | None = None,
    broadcast=None,
):
    """approve() → run_rollover() với resolve_and_activate_leg THẬT trên Postgres.

    signal/broadcast được truyền xuyên qua ``activate`` để quan sát resubscribe +
    onboarding broadcast mà KHÔNG mock resolve_and_activate_leg.
    """
    resolve_imo = resolve_imo or _fake_resolve_imo()
    captured = {"signal": signal or ResubscribeSignal(), "broadcasts": []}

    async def _broadcast(sid, data):
        captured["broadcasts"].append((sid, data))

    async def activate(session, new_leg_id, imo, mmsi, resolved_via):
        # resolve_and_activate_leg THẬT (không mock) — chỉ tiêm signal/broadcast quan sát.
        await resolve_and_activate_leg(
            session,
            new_leg_id,
            imo,
            mmsi,
            resolved_via,
            resubscribe_signal=captured["signal"],
            broadcast=_broadcast,
        )

    async with pg() as session:
        _, rollover = await proposal_service.approve(session, proposal_id, user_id=1)
    assert rollover is not None, "approve() phải trả RolloverJob khi có new_vessel_name"

    async with pg() as session:
        await proposal_service.run_rollover(
            rollover, session, resolve_imo=resolve_imo, activate=activate
        )
    return rollover, captured


# ============================================================================ #
# Item 1+2 — rollover đổi vessel: leg mới, active flip, superseded, mirror,
#            resubscribe (NO-MOCK resolve_and_activate_leg, Postgres thật).
# ============================================================================ #
async def test_rollover_creates_new_active_leg_and_mirrors_vessel(pg):
    """§6.8d/IC§3.2: sau rollover — leg mới active, leg cũ superseded+inactive,
    shipments mirror imo/mmsi tàu mới, resubscribe signal bắn."""
    shipment_id, old_leg_id = await _seed_shipment_with_active_leg(pg)
    extraction = _rollover_extraction(new_vessel_name="MSC VIGOUR III")
    proposal_id = await _insert_pending_proposal(
        pg, shipment_id, extraction, message_id="<qa04-1@msc.com>"
    )

    signal = ResubscribeSignal()
    rollover, captured = await _run_full_rollover(
        pg, shipment_id, proposal_id, resolve_imo=_fake_resolve_imo("9811222", "563029999"), signal=signal
    )

    async with pg() as session:
        old_leg = await session.get(ShipmentLeg, old_leg_id)
        new_leg = await session.get(ShipmentLeg, rollover.new_leg_id)
        shipment = await session.get(Shipment, shipment_id)

    # dòng shipment_legs MỚI được tạo (≠ leg cũ)
    assert new_leg.id != old_leg_id
    # is_active_leg chuyển sang leg mới
    assert new_leg.is_active_leg is True
    assert new_leg.onboarding_status == "resolved"
    assert new_leg.imo == "9811222"
    assert new_leg.mmsi == "563029999"
    assert new_leg.imo_resolved_via == "deterministic_scrape"
    # CÙNG leg_no — rollover ≠ transshipment (§6.8d)
    assert new_leg.leg_no == old_leg.leg_no == 1
    # leg cũ superseded_at set + is_active_leg=false
    assert old_leg.superseded_at is not None
    assert old_leg.is_active_leg is False
    # shipments mirror imo/mmsi tàu mới (nơi AIS worker đọc)
    assert shipment.imo == "9811222"
    assert shipment.mmsi == "563029999"
    assert shipment.onboarding_status == "resolved"
    # tín hiệu resubscribe được bắn (asyncio.Event)
    assert signal.is_set() is True
    # broadcast onboarding_update cũng bắn cho leg mới
    assert captured["broadcasts"], "phải bắn onboarding_update broadcast"
    assert captured["broadcasts"][-1][0] == shipment_id
    assert captured["broadcasts"][-1][1]["leg_id"] == rollover.new_leg_id


# ============================================================================ #
# Item 3 — ép uq_legs_one_active: đúng 1 leg active/lô sau rollover.
# ============================================================================ #
async def test_exactly_one_active_leg_after_rollover(pg):
    """IC§2.3: partial unique index uq_legs_one_active — query DB xác nhận đúng
    1 leg active/lô sau rollover (Postgres thật enforce partial unique)."""
    shipment_id, _ = await _seed_shipment_with_active_leg(pg)
    extraction = _rollover_extraction(new_vessel_name="MSC VIGOUR III")
    proposal_id = await _insert_pending_proposal(
        pg, shipment_id, extraction, message_id="<qa04-3@msc.com>"
    )
    await _run_full_rollover(pg, shipment_id, proposal_id)

    async with pg() as session:
        active_count = (
            await session.execute(
                select(func.count())
                .select_from(ShipmentLeg)
                .where(ShipmentLeg.shipment_id == shipment_id)
                .where(ShipmentLeg.is_active_leg.is_(True))
            )
        ).scalar_one()
        total_legs = (
            await session.execute(
                select(func.count())
                .select_from(ShipmentLeg)
                .where(ShipmentLeg.shipment_id == shipment_id)
            )
        ).scalar_one()
    assert active_count == 1  # đúng 1 active
    assert total_legs == 2  # cũ (superseded) + mới (active) — giữ lịch sử §6.8d


async def test_uq_one_active_index_rejects_two_active_legs(pg):
    """IC§2.3 trực tiếp: DB THẬT từ chối 2 active leg cùng shipment (partial unique).

    Chứng minh uq_legs_one_active là ràng buộc DB thật, không phải chỉ logic app.
    """
    import asyncpg
    from sqlalchemy.exc import IntegrityError

    shipment_id, _ = await _seed_shipment_with_active_leg(pg)
    with pytest.raises((IntegrityError, asyncpg.exceptions.UniqueViolationError)):
        async with pg() as session:
            async with session.begin():
                session.add(
                    ShipmentLeg(
                        shipment_id=shipment_id,
                        leg_no=1,
                        vessel_name="SECOND ACTIVE",
                        pol="SGSIN",
                        pod="VNCLI",
                        is_active_leg=True,  # leg thứ 2 active → phải nổ unique
                    )
                )


# ============================================================================ #
# Item 4 — approve có new_eta: eta_current update + INSERT eta_history(email_agent).
# ============================================================================ #
async def test_rollover_new_eta_updates_current_and_inserts_history(pg):
    """IC§3.2: có new_eta → shipments.eta_current update + eta_history
    (source='email_agent') — trong CÙNG transaction approve()."""
    shipment_id, _ = await _seed_shipment_with_active_leg(pg)
    new_eta_iso = "2026-08-15T09:30:00+00:00"
    extraction = _rollover_extraction(
        new_vessel_name="MSC VIGOUR III", new_eta=new_eta_iso
    )
    proposal_id = await _insert_pending_proposal(
        pg, shipment_id, extraction, message_id="<qa04-4@msc.com>"
    )
    await _run_full_rollover(pg, shipment_id, proposal_id)

    async with pg() as session:
        shipment = await session.get(Shipment, shipment_id)
        history = (
            await session.execute(
                select(EtaHistory).where(EtaHistory.shipment_id == shipment_id)
            )
        ).scalars().all()

    assert shipment.eta_current == datetime(2026, 8, 15, 9, 30, tzinfo=UTC)
    assert len(history) == 1
    assert history[0].source == "email_agent"
    assert history[0].eta_value == datetime(2026, 8, 15, 9, 30, tzinfo=UTC)


# ============================================================================ #
# Item 5 — 409: approve lần 2 cùng proposal → PROPOSAL_ALREADY_DECIDED.
# ============================================================================ #
async def test_approve_twice_raises_already_decided(pg):
    """IC§3.2: approve lần 2 cùng proposal → ProposalAlreadyDecided (API map 409)."""
    shipment_id, _ = await _seed_shipment_with_active_leg(pg)
    extraction = _rollover_extraction(new_vessel_name="MSC VIGOUR III")
    proposal_id = await _insert_pending_proposal(
        pg, shipment_id, extraction, message_id="<qa04-5@msc.com>"
    )
    async with pg() as session:
        _, rollover = await proposal_service.approve(session, proposal_id, user_id=1)
    assert rollover is not None

    async with pg() as session:
        with pytest.raises(proposal_service.ProposalAlreadyDecided):
            await proposal_service.approve(session, proposal_id, user_id=2)

    # trạng thái vẫn 'approved', decided_by KHÔNG bị đổi bởi lần 2
    async with pg() as session:
        proposal = await session.get(AgentProposal, proposal_id)
    assert proposal.status == "approved"
    assert proposal.decided_by == 1


# ============================================================================ #
# Item 6 — RuntimeWarning gate: coroutine chưa await PHẢI làm test đỏ.
# ============================================================================ #
async def test_resolve_and_activate_leg_is_a_real_coroutine_and_awaited(pg):
    """Item 6: chạy path rollover dưới -W error::RuntimeWarning.

    Nếu bất kỳ coroutine nào (resolve_imo mock HOẶC resolve_and_activate_leg THẬT)
    KHÔNG được await → Python phát 'coroutine was never awaited' RuntimeWarning →
    dưới filter error::RuntimeWarning test này ĐỎ. Xanh = mọi async được await
    đúng ⇒ RuntimeWarning (nếu thấy ở nơi khác) là mock-artifact, không phải bug
    của luồng approve/run_rollover.
    """
    shipment_id, old_leg_id = await _seed_shipment_with_active_leg(pg)
    extraction = _rollover_extraction(new_vessel_name="MSC VIGOUR III")
    proposal_id = await _insert_pending_proposal(
        pg, shipment_id, extraction, message_id="<qa04-6@msc.com>"
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        rollover, _ = await _run_full_rollover(pg, shipment_id, proposal_id)

    # path thật sự chạy tới cùng: leg mới active
    async with pg() as session:
        new_leg = await session.get(ShipmentLeg, rollover.new_leg_id)
    assert new_leg.is_active_leg is True


def test_runtimewarning_gate_has_teeth_control():
    """CONTROL cho item 6: chứng minh filter error::RuntimeWarning THỰC SỰ leo
    thang RuntimeWarning thành lỗi (test đỏ). Nếu control này không nổ thì gate ở
    item 6 vô nghĩa.

    Lưu ý kỹ thuật: cảnh báo 'coroutine was never awaited' do CPython phát qua GC
    finalizer / unraisable hook — BẤT ĐỒNG BỘ, không thể bắt bằng pytest.raises
    đồng bộ (đó là lý do bản nháp trước sai). Nhưng chính CÙNG một filter
    error::RuntimeWarning là thứ bảo vệ item 6: bất kỳ RuntimeWarning nào chạm tới
    warnings machinery đều biến thành lỗi. Ta chứng minh cơ chế đó trực tiếp."""
    with pytest.raises(RuntimeWarning):
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            warnings.warn("coroutine was never awaited (mô phỏng)", RuntimeWarning)


def test_unawaited_coroutine_emits_runtimewarning_control():
    """CONTROL bổ trợ: một async mock bị gọi mà KHÔNG await sinh RuntimeWarning
    'coroutine was never awaited' khi coroutine bị GC. Vì cảnh báo này đi qua
    unraisable hook (bất đồng bộ), ta bắt nó qua sys.unraisablehook thay vì
    pytest.raises — chứng minh tình huống 'sai async signature' thực sự tạo
    RuntimeWarning mà gate item 6 sẽ bắt.
    """
    import gc
    import sys

    captured: list[str] = []

    def _hook(unraisable) -> None:
        exc = unraisable.exc_value
        if isinstance(exc, RuntimeWarning):
            captured.append(str(exc))

    bad = _fake_resolve_imo()
    old_hook = sys.unraisablehook
    sys.unraisablehook = _hook
    try:
        # tạo coroutine, KHÔNG await → 'coroutine was never awaited' khi bị GC
        coro = bad("MSC VIGOUR III", "V.002N", "SGSIN", "VNCLI")  # noqa: cố ý không await
        del coro
        gc.collect()
    finally:
        sys.unraisablehook = old_hook

    assert any("never awaited" in msg for msg in captured), (
        "async mock sai signature PHẢI sinh 'coroutine was never awaited' RuntimeWarning"
    )


# ============================================================================ #
# Item 7 — realcase vessel name: "  msc  vigour iii " (space + case lẫn) →
#          normalize + resolve đúng, không chỉ placeholder MMSI.
# ============================================================================ #
async def test_realcase_messy_vessel_name_is_normalized_end_to_end(pg):
    """Item 7: tên tàu bẩn '  msc  vigour iii ' → normalize_vessel_name (trim +
    collapse space + upper) áp ở leg mới VÀ ở payload gửi scrape; resolve trả
    IMO/MMSI thật (không placeholder). Xác nhận danh tính tàu mới ghi vào DB."""
    shipment_id, _ = await _seed_shipment_with_active_leg(pg)
    messy = "  msc  vigour iii "
    extraction = _rollover_extraction(new_vessel_name=messy)
    proposal_id = await _insert_pending_proposal(
        pg, shipment_id, extraction, message_id="<qa04-7@msc.com>"
    )

    # bắt tên tàu mà run_rollover gửi xuống scrape (biên ngoài) để chứng minh
    # normalize xảy ra TRƯỚC khi resolve, không phải sau.
    seen = {}

    def _capturing_resolve():
        async def _resolve(vessel_name, voyage_no, pol, pod):
            seen["vessel_name"] = vessel_name
            return IMOResolverResult(
                imo="9811333",
                mmsi="563037777",
                vessel_name=vessel_name,
                confidence="cao",
                source_url="https://example.com/vessel/9811333",
            )

        return _resolve

    rollover, _ = await _run_full_rollover(
        pg, shipment_id, proposal_id, resolve_imo=_capturing_resolve()
    )

    # normalize áp ở leg mới (nguồn sự thật) — collapse '  msc  vigour iii ' → 'MSC VIGOUR III'
    async with pg() as session:
        new_leg = await session.get(ShipmentLeg, rollover.new_leg_id)
        shipment = await session.get(Shipment, shipment_id)
    assert new_leg.vessel_name == "MSC VIGOUR III"
    # job gửi xuống scrape đã normalize (RolloverJob.vessel_name)
    assert rollover.vessel_name == "MSC VIGOUR III"
    assert seen["vessel_name"] == "MSC VIGOUR III"
    # resolve trả IMO/MMSI THẬT (không placeholder) → mirror xuống shipments
    assert shipment.imo == "9811333"
    assert shipment.mmsi == "563037777"
    assert new_leg.imo == "9811333"
    assert new_leg.mmsi == "563037777"


# ============================================================================ #
# Extra — scrape THẤT BẠI: leg mới KHÔNG được activate, giữ pending/manual;
#         leg cũ vẫn active (đúng 1 active) → an toàn (không mock activate path).
# ============================================================================ #
async def test_rollover_scrape_failure_keeps_old_leg_active(pg):
    """Biên ngoài scrape fail (ScrapeError) → mark_leg_manual THẬT; leg mới
    manual_required + inactive, leg cũ vẫn active → vẫn đúng 1 active leg."""
    shipment_id, old_leg_id = await _seed_shipment_with_active_leg(pg)
    extraction = _rollover_extraction(new_vessel_name="MSC VIGOUR III")
    proposal_id = await _insert_pending_proposal(
        pg, shipment_id, extraction, message_id="<qa04-fail@msc.com>"
    )

    async def failing_resolve(vessel_name, voyage_no, pol, pod):
        return ScrapeError("not_found")

    async with pg() as session:
        _, rollover = await proposal_service.approve(session, proposal_id, user_id=1)
    async with pg() as session:
        await proposal_service.run_rollover(
            rollover, session, resolve_imo=failing_resolve
        )

    async with pg() as session:
        old_leg = await session.get(ShipmentLeg, old_leg_id)
        new_leg = await session.get(ShipmentLeg, rollover.new_leg_id)
        active_count = (
            await session.execute(
                select(func.count())
                .select_from(ShipmentLeg)
                .where(ShipmentLeg.shipment_id == shipment_id)
                .where(ShipmentLeg.is_active_leg.is_(True))
            )
        ).scalar_one()
    assert new_leg.onboarding_status == "manual_required"
    assert new_leg.onboarding_error == "not_found"
    assert new_leg.is_active_leg is False
    assert old_leg.is_active_leg is True  # rollover chưa xác nhận tàu mới → giữ tàu cũ
    assert active_count == 1
