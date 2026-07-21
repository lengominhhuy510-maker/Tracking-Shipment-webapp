"""TDD tests for app.workers.ais.parser — pure parse/validate, offline."""

import json
from datetime import UTC
from pathlib import Path

import pytest

from app.workers.ais.parser import AisPosition, parse_ais_message

FIXTURE = Path(__file__).parent / "fixtures" / "ais_positions.json"


@pytest.fixture
def raw_messages() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_all_fixture_messages(raw_messages):
    parsed = [parse_ais_message(m) for m in raw_messages]
    assert all(isinstance(p, AisPosition) for p in parsed)
    assert len(parsed) == len(raw_messages)


def test_parse_fields_and_units(raw_messages):
    pos = parse_ais_message(raw_messages[0])
    assert pos is not None
    assert pos.mmsi == "570000001"
    assert pos.lat == pytest.approx(10.34521)
    assert pos.lon == pytest.approx(107.07713)
    # SOG in knots, COG in degrees — raw aisstream values pass through unscaled
    assert pos.sog == pytest.approx(11.2)
    assert pos.cog == pytest.approx(128.4)
    assert pos.timestamp.tzinfo is not None
    assert pos.timestamp.utcoffset().total_seconds() == 0
    assert pos.timestamp.astimezone(UTC).year == 2026


def test_missing_position_report_skipped():
    assert parse_ais_message({"MessageType": "ShipStaticData", "Message": {}}) is None
    assert parse_ais_message({"Message": {}}) is None
    assert parse_ais_message({}) is None


def test_unavailable_sog_cog_become_none(raw_messages):
    msg = json.loads(json.dumps(raw_messages[0]))
    msg["Message"]["PositionReport"]["Sog"] = 102.3
    msg["Message"]["PositionReport"]["Cog"] = 360.0
    pos = parse_ais_message(msg)
    assert pos is not None
    assert pos.sog is None
    assert pos.cog is None


def test_invalid_coordinates_skipped(raw_messages):
    msg = json.loads(json.dumps(raw_messages[0]))
    msg["Message"]["PositionReport"]["Latitude"] = 91.0
    assert parse_ais_message(msg) is None
