"""QA-06 — REST contract: error envelope, PATCH whitelist/blacklist, 400 vs 422, 404/409, 401.

REPORT-ONLY (evidence-based). Nguồn chân lý:
- IC§3.1 (Interface-Contract_v0.9.9.md): error envelope `{"detail": {"code","message"}}`;
  422 GIỮ NGUYÊN shape list Pydantic mặc định; status code (200/201/400/401/403/404/409/422/500);
  danh mục 10 code = SHIPMENT_NOT_FOUND, PROPOSAL_NOT_FOUND, PROPOSAL_ALREADY_DECIDED,
  FINDING_NOT_FOUND, IMMUTABLE_FIELD, UNSUPPORTED_INCOTERM_COMBINATION, INVALID_CONTAINER_NO,
  ONBOARDING_NOT_RETRYABLE, UNAUTHENTICATED, FORBIDDEN. 401 = JSON, KHÔNG server-redirect.
- IC§3.2 (bảng endpoint + PATCH whitelist/blacklist):
    Whitelist (sửa được): eta_original (+tự set eta_original_source=manual), atd,
      pol/pod (chỉ khi atd IS NULL), status, bl_number, carrier.
    Blacklist (400 IMMUTABLE_FIELD): imo, mmsi, onboarding_* (mirror), monitoring_mode (derived),
      incoterm, shipment_direction, eta_current (chỉ engine/proposal), current_* (chỉ AIS worker).

Kiểm READ-ONLY qua httpx.AsyncClient + dependency_overrides[get_current_user] (conftest auth_override),
in-memory SQLite seeded 4 lô (app.db.seed). Test 401 KHÔNG áp override (không cookie).
"""

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_current_user, get_session
from app.db.base import Base
from app.db.models import AgentProposal
from app.db.seed import seed
from app.main import app

# --------------------------------------------------------------------------- #
# Nguồn chân lý viết cứng ở test (KHÔNG import từ code — để phát hiện drift)     #
# --------------------------------------------------------------------------- #

# Danh mục 10 code IC§3.1
IC_CODE_CATALOG = {
    "SHIPMENT_NOT_FOUND",
    "PROPOSAL_NOT_FOUND",
    "PROPOSAL_ALREADY_DECIDED",
    "FINDING_NOT_FOUND",
    "IMMUTABLE_FIELD",
    "UNSUPPORTED_INCOTERM_COMBINATION",
    "INVALID_CONTAINER_NO",
    "ONBOARDING_NOT_RETRYABLE",
    "UNAUTHENTICATED",
    "FORBIDDEN",
}

# PATCH blacklist IC§3.2 → 400 IMMUTABLE_FIELD (vét cạn nhóm)
PATCH_FORBIDDEN_FIELDS = [
    "imo",
    "mmsi",
    "onboarding_status",   # onboarding_* mirror
    "onboarding_error",    # onboarding_* mirror
    "monitoring_mode",     # derived
    "incoterm",            # đổi = tạo lô mới
    "shipment_direction",  # đổi = tạo lô mới
    "eta_current",         # chỉ engine/proposal
    "current_lat",         # current_* chỉ AIS worker
    "current_lon",
    "current_sog",
    "current_cog",
]


def _aware(y, mo, d, h=0, mi=0) -> str:
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).isoformat()


def _create_payload(**overrides) -> dict:
    """Payload POST hợp lệ. imo+mmsi để resolve inline (không spawn scrape network)."""
    payload = {
        "bl_number": "BL-QA06-1",
        "container_no": "CSQU3054383",
        "shipment_direction": "import",
        "incoterm": "FOB",
        "carrier": "Maersk",
        "vessel_name": "QA06 VESSEL",
        "voyage_no": "V.900N",
        "pol": "SGSIN Singapore",
        "pod": "VNCLI Cat Lai",
        "imo": "9321483",
        "mmsi": "477220100",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# Fixtures                                                                      #
# --------------------------------------------------------------------------- #


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        async with s.begin():
            await seed(s)
        # Seed proposals: #A pending, #B đã 'approved' (cho test 409).
        async with s.begin():
            s.add(
                AgentProposal(
                    id=1001,
                    shipment_id=1,
                    source_email_id="qa06-pending@maersk.com",
                    extracted_json=None,
                    proposed_action="test-pending",
                    status="pending",
                )
            )
            s.add(
                AgentProposal(
                    id=1002,
                    shipment_id=1,
                    source_email_id="qa06-decided@maersk.com",
                    extracted_json=None,
                    proposed_action="test-decided",
                    status="approved",
                    decided_by=1,
                )
            )
    yield factory
    await engine.dispose()


@pytest.fixture
async def client(db, auth_override):
    """Client CÓ auth override (get_current_user → User id=1)."""
    async def override_session():
        async with db() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def noauth_client(db):
    """Client KHÔNG áp auth override — dùng cho test 401 không cookie (IC§3.1)."""
    async def override_session():
        async with db() as session:
            yield session

    # Đảm bảo KHÔNG có override get_current_user còn sót.
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Helpers khẳng định shape envelope                                            #
# --------------------------------------------------------------------------- #


def assert_error_envelope(resp, expected_code: str, expected_status: int) -> None:
    """IC§3.1: lỗi nghiệp vụ = JSON {"detail": {"code","message"}}, code ∈ danh mục."""
    assert resp.status_code == expected_status, resp.text
    ctype = resp.headers.get("content-type", "")
    assert "application/json" in ctype, f"content-type không JSON: {ctype!r} — {resp.text[:200]}"
    body = resp.json()
    assert isinstance(body, dict) and "detail" in body, body
    detail = body["detail"]
    assert isinstance(detail, dict), f"detail phải là object (không list/str): {detail!r}"
    assert set(("code", "message")).issubset(detail.keys()), detail
    assert detail["code"] == expected_code, detail
    assert detail["code"] in IC_CODE_CATALOG, f"code ngoài danh mục IC§3.1: {detail['code']}"
    assert isinstance(detail["message"], str) and detail["message"], detail


# =========================================================================== #
# 1. PATCH BLACKLIST — mọi field cấm → 400 IMMUTABLE_FIELD (vét cạn)           #
# =========================================================================== #


@pytest.mark.parametrize("field", PATCH_FORBIDDEN_FIELDS)
async def test_patch_forbidden_field_400_immutable(client, field):
    r = await client.patch("/api/v1/shipments/1", json={field: "x"})
    assert_error_envelope(r, "IMMUTABLE_FIELD", 400)


# =========================================================================== #
# 2. PATCH WHITELIST — mỗi field hợp lệ → 200 + side-effect đúng               #
# =========================================================================== #


async def test_patch_eta_original_200_sets_source_manual(client):
    r = await client.patch("/api/v1/shipments/1", json={"eta_original": _aware(2026, 8, 1)})
    assert r.status_code == 200, r.text
    assert r.json()["eta_original_source"] == "manual"


async def test_patch_atd_200(client):
    # Lô 1 status=on_sea, atd đã set — cập nhật atd mới hợp lệ → 200.
    r = await client.patch("/api/v1/shipments/1", json={"atd": _aware(2026, 7, 20, 12)})
    assert r.status_code == 200, r.text


async def test_patch_status_forward_arrived_200(client):
    r = await client.patch("/api/v1/shipments/1", json={"status": "arrived"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "arrived"


async def test_patch_status_delivered_200_sets_delivered_at(client):
    r = await client.patch("/api/v1/shipments/1", json={"status": "delivered"})
    assert r.status_code == 200, r.text
    assert r.json()["delivered_at"] is not None


async def test_patch_status_backward_200(client):
    # Lô 1 on_sea → quay lui 'new' (IC§0.3 cho phép quay lui) → 200.
    r = await client.patch("/api/v1/shipments/1", json={"status": "new"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "new"


async def test_patch_bl_number_200(client):
    r = await client.patch("/api/v1/shipments/1", json={"bl_number": "BL-QA06-PATCHED"})
    assert r.status_code == 200, r.text
    assert r.json()["bl_number"] == "BL-QA06-PATCHED"


async def test_patch_carrier_200(client):
    r = await client.patch("/api/v1/shipments/1", json={"carrier": "Evergreen"})
    assert r.status_code == 200, r.text
    assert r.json()["carrier"] == "Evergreen"


# --------------------------------------------------------------------------- #
# 2b. pol/pod — chỉ khi atd IS NULL (IC§3.2)                                    #
# --------------------------------------------------------------------------- #


async def test_patch_pol_400_when_atd_set(client):
    # Lô 1 có atd (seed) → pol → 400 IMMUTABLE_FIELD.
    r = await client.patch("/api/v1/shipments/1", json={"pol": "HKHKG Hong Kong"})
    assert_error_envelope(r, "IMMUTABLE_FIELD", 400)


async def test_patch_pod_400_when_atd_set(client):
    r = await client.patch("/api/v1/shipments/1", json={"pod": "HKHKG Hong Kong"})
    assert_error_envelope(r, "IMMUTABLE_FIELD", 400)


async def test_patch_pol_pod_200_when_atd_null(client):
    # Tạo lô mới (status=new, atd=NULL) → PATCH pol/pod → 200.
    created = await client.post("/api/v1/shipments/", json=_create_payload(bl_number="BL-QA06-NOATD"))
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    assert created.json()["atd"] is None

    r = await client.patch(f"/api/v1/shipments/{sid}", json={"pol": "HKHKG Hong Kong"})
    assert r.status_code == 200, r.text
    assert r.json()["pol"] == "HKHKG Hong Kong"

    r = await client.patch(f"/api/v1/shipments/{sid}", json={"pod": "TWKHH Kaohsiung"})
    assert r.status_code == 200, r.text
    assert r.json()["pod"] == "TWKHH Kaohsiung"


# =========================================================================== #
# 3. POST — 400 nghiệp vụ (KHÔNG 422)                                          #
# =========================================================================== #


async def test_post_bad_container_400_invalid_container_no(client):
    # Sai check-digit ISO 6346 → 400 INVALID_CONTAINER_NO (route layer, KHÔNG 422).
    r = await client.post("/api/v1/shipments/", json=_create_payload(container_no="CSQU3054384"))
    assert_error_envelope(r, "INVALID_CONTAINER_NO", 400)


async def test_post_bad_format_container_400_invalid_container_no(client):
    # Sai format hoàn toàn → vẫn 400 INVALID_CONTAINER_NO (không phải 422).
    r = await client.post("/api/v1/shipments/", json=_create_payload(container_no="NOTACONTAINER"))
    assert_error_envelope(r, "INVALID_CONTAINER_NO", 400)


async def test_post_export_ef_400_unsupported_incoterm(client):
    # export × FOB (nhóm E/F) → 400 UNSUPPORTED_INCOTERM_COMBINATION.
    r = await client.post(
        "/api/v1/shipments/",
        json=_create_payload(shipment_direction="export", incoterm="FOB"),
    )
    assert_error_envelope(r, "UNSUPPORTED_INCOTERM_COMBINATION", 400)


# =========================================================================== #
# 4. 404 / 409 / retry-onboarding                                             #
# =========================================================================== #


async def test_get_404_shipment_not_found(client):
    r = await client.get("/api/v1/shipments/999999")
    assert_error_envelope(r, "SHIPMENT_NOT_FOUND", 404)


async def test_patch_404_shipment_not_found(client):
    r = await client.patch("/api/v1/shipments/999999", json={"carrier": "X"})
    assert_error_envelope(r, "SHIPMENT_NOT_FOUND", 404)


async def test_approve_404_proposal_not_found(client):
    r = await client.post("/api/v1/agent-proposals/999999/approve")
    assert_error_envelope(r, "PROPOSAL_NOT_FOUND", 404)


async def test_reject_404_proposal_not_found(client):
    r = await client.post("/api/v1/agent-proposals/999999/reject", json={"reason": "x"})
    assert_error_envelope(r, "PROPOSAL_NOT_FOUND", 404)


async def test_approve_409_already_decided(client):
    # Proposal #1002 seed status='approved' → approve lại → 409.
    r = await client.post("/api/v1/agent-proposals/1002/approve")
    assert_error_envelope(r, "PROPOSAL_ALREADY_DECIDED", 409)


async def test_reject_409_already_decided(client):
    r = await client.post("/api/v1/agent-proposals/1002/reject", json={"reason": "x"})
    assert_error_envelope(r, "PROPOSAL_ALREADY_DECIDED", 409)


async def test_retry_onboarding_400_not_retryable(client):
    # Seed legs 'resolved' → không manual_required → 400 ONBOARDING_NOT_RETRYABLE.
    r = await client.post("/api/v1/shipments/1/retry-onboarding")
    assert_error_envelope(r, "ONBOARDING_NOT_RETRYABLE", 400)


async def test_retry_onboarding_404_shipment_not_found(client):
    r = await client.post("/api/v1/shipments/999999/retry-onboarding")
    assert_error_envelope(r, "SHIPMENT_NOT_FOUND", 404)


# =========================================================================== #
# 5. 422 — GIỮ NGUYÊN shape list Pydantic mặc định (IC§3.1)                    #
# =========================================================================== #


def assert_pydantic_422(resp) -> None:
    """422 = shape list Pydantic mặc định: {"detail": [ {...}, ... ]}."""
    assert resp.status_code == 422, resp.text
    assert "application/json" in resp.headers.get("content-type", "")
    body = resp.json()
    assert isinstance(body, dict) and "detail" in body, body
    assert isinstance(body["detail"], list), f"422 phải giữ shape list, nhận: {body['detail']!r}"
    assert body["detail"], "danh sách lỗi Pydantic không được rỗng"


async def test_post_missing_required_field_422_list_shape(client):
    payload = _create_payload()
    del payload["bl_number"]  # thiếu field bắt buộc
    r = await client.post("/api/v1/shipments/", json=payload)
    assert_pydantic_422(r)


async def test_post_bad_imo_pattern_422_not_400(client):
    # imo là field ĐƯỢC khai trong ShipmentCreate với pattern → sai pattern = 422 Pydantic,
    # KHÔNG phải 400 (phân biệt validation Pydantic vs nghiệp vụ).
    r = await client.post("/api/v1/shipments/", json=_create_payload(imo="123", mmsi="477220100"))
    assert_pydantic_422(r)


async def test_patch_naive_datetime_422_list_shape(client):
    # atd whitelist nhưng giá trị naive datetime → validator raise → 422 (giữ list shape).
    r = await client.patch("/api/v1/shipments/1", json={"atd": "2026-07-20T12:00:00"})
    assert_pydantic_422(r)


# =========================================================================== #
# 6. 401 — không cookie → UNAUTHENTICATED JSON, KHÔNG redirect (IC§3.1)         #
# =========================================================================== #


async def test_no_cookie_401_unauthenticated_json(noauth_client):
    r = await noauth_client.get("/api/v1/shipments/")
    # KHÔNG server-redirect (không 3xx).
    assert r.status_code == 401, f"kỳ vọng 401, nhận {r.status_code}"
    assert not (300 <= r.status_code < 400), "KHÔNG được redirect (IC§3.1)"
    assert "location" not in {k.lower() for k in r.headers.keys()}, "không được có Location header"
    assert_error_envelope(r, "UNAUTHENTICATED", 401)


async def test_no_cookie_401_on_detail_endpoint(noauth_client):
    r = await noauth_client.get("/api/v1/shipments/1")
    assert_error_envelope(r, "UNAUTHENTICATED", 401)


async def test_no_cookie_401_on_proposals(noauth_client):
    r = await noauth_client.get("/api/v1/agent-proposals")
    assert_error_envelope(r, "UNAUTHENTICATED", 401)


# =========================================================================== #
# 7. Envelope phổ quát — MỌI lỗi nghiệp vụ có shape đúng, code ∈ danh mục       #
# =========================================================================== #


async def test_all_business_errors_share_envelope_and_catalog(client):
    """Quét ma trận lỗi nghiệp vụ → mọi response là JSON envelope, code ∈ danh mục IC§3.1,
    không HTML/500 trần."""
    cases = [
        ("GET", "/api/v1/shipments/999999", None, 404, "SHIPMENT_NOT_FOUND"),
        ("PATCH", "/api/v1/shipments/1", {"imo": "1"}, 400, "IMMUTABLE_FIELD"),
        ("POST", "/api/v1/shipments/", _create_payload(container_no="BADX0000000"), 400, "INVALID_CONTAINER_NO"),
        ("POST", "/api/v1/shipments/", _create_payload(shipment_direction="export", incoterm="FOB"), 400, "UNSUPPORTED_INCOTERM_COMBINATION"),
        ("POST", "/api/v1/shipments/1/retry-onboarding", None, 400, "ONBOARDING_NOT_RETRYABLE"),
        ("POST", "/api/v1/agent-proposals/999999/approve", None, 404, "PROPOSAL_NOT_FOUND"),
        ("POST", "/api/v1/agent-proposals/1002/approve", None, 409, "PROPOSAL_ALREADY_DECIDED"),
    ]
    for method, path, body, status, code in cases:
        resp = await client.request(method, path, json=body)
        assert resp.status_code < 500, f"{method} {path} trả 5xx: {resp.status_code} {resp.text[:200]}"
        assert_error_envelope(resp, code, status)
