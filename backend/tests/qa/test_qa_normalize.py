"""QA-03 — normalize.py: vessel/container normalization + ISO 6346 check-digit
+ HTTP boundary 400 INVALID_CONTAINER_NO (never 422 Pydantic).

Source of truth: IC§9 (2 shared normalize functions + canonical examples),
IC§3.1 (400 INVALID_CONTAINER_NO for business errors, 422 only for Pydantic).

REPORT-ONLY QA suite. Read-only against app code; no app/** edits.
Run from backend/ with AIS_MODE=replay.
"""

import string

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_session
from app.core.normalize import normalize_container_no, normalize_vessel_name
from app.db.base import Base
from app.db.seed import seed
from app.main import app

# --------------------------------------------------------------------------- #
# Independent reference implementation of the ISO 6346 check digit, derived
# straight from the standard (NOT imported from app) so the assertion is an
# external oracle, not a tautology against the code under test.
# --------------------------------------------------------------------------- #
_LETTER_VALUES = {}
_v = 10
for _ch in string.ascii_uppercase:
    if _v % 11 == 0:
        _v += 1
    _LETTER_VALUES[_ch] = _v
    _v += 1


def _iso6346_check_digit(base10: str) -> int:
    """Reference: sum(value * 2**position) over first 10 chars, mod 11, fold 10->0."""
    total = 0
    for i, ch in enumerate(base10):
        value = _LETTER_VALUES[ch] if ch.isalpha() else int(ch)
        total += value * (2**i)
    return (total % 11) % 10


def _valid_container(base10: str) -> str:
    return base10 + str(_iso6346_check_digit(base10))


# ============================ vessel name ================================== #


class TestNormalizeVesselName:
    def test_ic9_canonical_example(self):
        # IC§9: "  ever  Given " -> "EVER GIVEN"
        assert normalize_vessel_name("  ever  Given ") == "EVER GIVEN"

    def test_collapses_tabs_and_newlines(self):
        assert normalize_vessel_name("\tEver\t\nGiven\n") == "EVER GIVEN"

    def test_already_normalized_is_idempotent(self):
        assert normalize_vessel_name("EVER GIVEN") == "EVER GIVEN"
        assert normalize_vessel_name(normalize_vessel_name("  a  b ")) == "A B"

    def test_multiple_internal_spaces_collapse_to_one(self):
        assert normalize_vessel_name("MAERSK      ESSEX") == "MAERSK ESSEX"

    def test_empty_and_whitespace_only(self):
        assert normalize_vessel_name("") == ""
        assert normalize_vessel_name("   \t\n ") == ""


# ============================ container: valid ============================= #


class TestNormalizeContainerValid:
    def test_ic9_canonical_csqu(self):
        # IC§9 canonical: "csqu 305438-3" -> "CSQU3054383" (check digit 3)
        assert normalize_container_no("csqu 305438-3") == "CSQU3054383"

    def test_already_clean_valid(self):
        assert normalize_container_no("CSQU3054383") == "CSQU3054383"

    def test_lowercase_upcased(self):
        assert normalize_container_no("csqu3054383") == "CSQU3054383"

    def test_strips_hyphens_and_all_whitespace(self):
        assert normalize_container_no(" c s q u-3054383 ") == "CSQU3054383"
        assert normalize_container_no("CSQU-3054-383") == "CSQU3054383"

    @pytest.mark.parametrize(
        "base10",
        ["CSQU305438", "MSKU044726", "TCLU123456", "GATU000000", "HLXU123456"],
    )
    def test_reference_valid_containers_pass(self, base10):
        full = _valid_container(base10)
        assert normalize_container_no(full) == full

    def test_check_digit_remainder_10_folds_to_0(self):
        # ISO 6346: when sum % 11 == 10, the check digit is 0 (10 folds to 0).
        base10 = "ABCU000007"
        assert _iso6346_check_digit(base10) == 0
        full = base10 + "0"
        assert normalize_container_no(full) == full

    def test_check_digit_algorithm_matches_reference_both_directions(self):
        # Round-trip: for every reference-valid number, app accepts; and for
        # every OTHER final digit, app rejects (algorithm agrees both ways).
        for base10 in ["CSQU305438", "MSKU044726", "GATU000000"]:
            good = _iso6346_check_digit(base10)
            assert normalize_container_no(base10 + str(good)) == base10 + str(good)
            for wrong in range(10):
                if wrong == good:
                    continue
                with pytest.raises(ValueError):
                    normalize_container_no(base10 + str(wrong))


# ========================= container: invalid ============================= #


class TestNormalizeContainerInvalid:
    def test_wrong_check_digit_raises(self):
        # CSQU3054384 — correct check digit is 3, not 4.
        with pytest.raises(ValueError):
            normalize_container_no("CSQU3054384")

    def test_three_letters_bad_format(self):
        with pytest.raises(ValueError):
            normalize_container_no("ABC12345678")

    def test_too_short(self):
        with pytest.raises(ValueError):
            normalize_container_no("CSQU305438")  # 10 chars, missing check digit

    def test_too_long(self):
        with pytest.raises(ValueError):
            normalize_container_no("CSQU30543833")

    def test_digit_in_letter_zone(self):
        with pytest.raises(ValueError):
            normalize_container_no("C5QU3054383")

    def test_letter_in_digit_zone(self):
        with pytest.raises(ValueError):
            normalize_container_no("CSQUO054383")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            normalize_container_no("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            normalize_container_no("   -  ")

    def test_exotic_characters_raise(self):
        with pytest.raises(ValueError):
            normalize_container_no("CSQU30543#3")
        with pytest.raises(ValueError):
            normalize_container_no("CS QU3054383X")

    def test_five_letters_prefix(self):
        with pytest.raises(ValueError):
            normalize_container_no("CSQUX054383")


# ==================== HTTP boundary: 400 not 422 ========================== #
# POST a shipment with a bad container through the REAL route. The route must
# catch ValueError from normalize_container_no and raise 400 INVALID_CONTAINER_NO
# (IC§3.1) — it must NOT fall through to a 422 Pydantic error, because
# container_no is declared as a plain str in ShipmentCreate (validated at the
# route layer, not by Pydantic).


@pytest.fixture
async def http_db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        async with s.begin():
            await seed(s)
    yield factory
    await engine.dispose()


@pytest.fixture
async def http_client(http_db, auth_override):
    async def override_session():
        async with http_db() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _payload(**overrides) -> dict:
    payload = {
        "bl_number": "BL-QA03",
        "container_no": "csqu 305438-3",
        "shipment_direction": "import",
        "incoterm": "FOB",
        "carrier": "Maersk",
        "vessel_name": "  ever  Given ",
        "voyage_no": "V.900N",
        "pol": "SGSIN Singapore",
        "pod": "VNCLI Cat Lai",
    }
    payload.update(overrides)
    return payload


class TestHttpBoundary:
    async def test_valid_container_201_and_normalized(self, http_client):
        r = await http_client.post("/api/v1/shipments/", json=_payload())
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["container_no"] == "CSQU3054383"
        assert body["vessel_name"] == "EVER GIVEN"

    async def test_bad_check_digit_is_400_invalid_container_not_422(self, http_client):
        r = await http_client.post(
            "/api/v1/shipments/", json=_payload(container_no="CSQU3054384")
        )
        assert r.status_code == 400, r.text
        assert r.status_code != 422
        assert r.json()["detail"]["code"] == "INVALID_CONTAINER_NO"

    async def test_bad_format_is_400_invalid_container_not_422(self, http_client):
        r = await http_client.post(
            "/api/v1/shipments/", json=_payload(container_no="ABC12345678")
        )
        assert r.status_code == 400, r.text
        assert r.status_code != 422
        assert r.json()["detail"]["code"] == "INVALID_CONTAINER_NO"

    async def test_empty_container_is_400_invalid_container_not_422(self, http_client):
        # Empty string is a valid str for Pydantic (no 422); the route's
        # normalize call must reject it as 400 INVALID_CONTAINER_NO.
        r = await http_client.post(
            "/api/v1/shipments/", json=_payload(container_no="")
        )
        assert r.status_code == 400, r.text
        assert r.status_code != 422
        assert r.json()["detail"]["code"] == "INVALID_CONTAINER_NO"
