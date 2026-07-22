"""TDD tests for Agent B research cache + caps (TASK-09, IC§5.2, §6.3c/d)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents import agent_b, tools
from app.config import settings
from app.db.base import Base
from app.db.models import ResearchFinding, Shipment, User
from app.services import research_service

VALID_JSON = (
    '{"event": "Bão nhiệt đới gần eo Luzon", "relevance": "cao",'
    ' "route_impact": "có thể chậm 12-24h", "confidence": "trung_binh",'
    ' "sources": ["https://news.example.com/storm"]}'
)


class FakeRunner:
    """Stands in for the Agent B AG2Runner — replays canned replies."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls = 0

    async def run(self, message: str) -> str:
        self.calls += 1
        return self.replies[min(self.calls - 1, len(self.replies) - 1)]


@pytest.fixture
async def db(monkeypatch: pytest.MonkeyPatch):
    wpi = Path(__file__).parents[1] / "data" / "wpi_ports.csv"
    monkeypatch.setattr(settings, "WPI_DATA_PATH", str(wpi))
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(research_service, "async_session_factory", factory)
    monkeypatch.setattr(tools, "async_session_factory", factory)
    research_service.reset_hard_cap()
    yield factory
    research_service.reset_hard_cap()
    await engine.dispose()


def _shipment(bl: str = "BL-R1", **overrides) -> Shipment:
    fields = dict(
        bl_number=bl,
        container_no="CSQU3054383",
        incoterm="FOB",
        shipment_direction="import",
        monitoring_mode="auto_email",
        carrier="Maersk",
        vessel_name="TEST VESSEL",
        pol="SGSIN Singapore",
        pod="VNCLI Cat Lai",
        status="on_sea",
        onboarding_status="resolved",
        eta_current=datetime(2026, 7, 24, 12, tzinfo=UTC),
    )
    fields.update(overrides)
    return Shipment(**fields)


async def _seed_shipment(factory, shipment: Shipment | None = None) -> int:
    async with factory() as session:
        row = shipment or _shipment()
        session.add(row)
        await session.commit()
        return row.id


async def _seed_finding(
    factory,
    shipment_id: int,
    *,
    route_key: str = "SGSIN-VNCLI",
    age_hours: float = 1.0,
    event: str = "cached: tắc cảng Cát Lái",
) -> int:
    async with factory() as session:
        row = ResearchFinding(
            shipment_id=shipment_id,
            route_key=route_key,
            event=event,
            relevance="cao",
            route_impact="chậm 6h",
            confidence="cao",
            sources=["https://news.example.com/cached"],
            created_at=datetime.now(UTC) - timedelta(hours=age_hours),
        )
        session.add(row)
        await session.commit()
        return row.id


def _forbid_agent_b(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise AssertionError("Agent B must NOT run on cache hit (§6.3d)")

    monkeypatch.setattr(research_service.agent_b, "build_agent_b", boom)


# --- cache (§6.3d): hit trả thẳng, KHÔNG gọi Agent B / search ---


async def test_cache_hit_returns_cached_without_calling_agent_b(db, monkeypatch) -> None:
    shipment_id = await _seed_shipment(db)
    await _seed_finding(db, shipment_id, age_hours=1.0)
    _forbid_agent_b(monkeypatch)

    finding = await research_service.request_research(shipment_id)

    assert finding.event == "cached: tắc cảng Cát Lái"
    assert finding.confidence == "cao"


async def test_cache_hit_shared_across_shipments_same_route(db, monkeypatch) -> None:
    first = await _seed_shipment(db, _shipment("BL-R1"))
    second = await _seed_shipment(db, _shipment("BL-R2"))
    await _seed_finding(db, first, age_hours=2.0)
    _forbid_agent_b(monkeypatch)

    finding = await research_service.request_research(second)

    assert finding.event == "cached: tắc cảng Cát Lái"


async def test_cache_hit_even_with_focus(db, monkeypatch) -> None:
    shipment_id = await _seed_shipment(db)
    await _seed_finding(db, shipment_id, age_hours=1.0)
    _forbid_agent_b(monkeypatch)

    finding = await research_service.request_research(shipment_id, focus="eo Malacca 48h")

    assert finding.event == "cached: tắc cảng Cát Lái"


async def test_stale_cache_misses_and_runs_agent_b_then_persists(db, monkeypatch) -> None:
    shipment_id = await _seed_shipment(db)
    await _seed_finding(db, shipment_id, age_hours=settings.RESEARCH_CADENCE_HOURS + 1)
    runner = FakeRunner([VALID_JSON])
    monkeypatch.setattr(research_service.agent_b, "build_agent_b", lambda: runner)

    finding = await research_service.request_research(shipment_id)

    assert runner.calls == 1
    assert finding.event == "Bão nhiệt đới gần eo Luzon"
    async with db() as session:
        rows = (
            (await session.execute(select(ResearchFinding).order_by(ResearchFinding.id)))
            .scalars()
            .all()
        )
        assert len(rows) == 2  # stale row + new persisted row
        new = rows[-1]
        assert new.route_key == "SGSIN-VNCLI"
        assert new.verified is False
        assert new.event == "Bão nhiệt đới gần eo Luzon"
        assert new.sources == ["https://news.example.com/storm"]


# --- JSON mode + retry 1 lần (§6.3c, IC§5.2) ---


async def test_invalid_json_retries_once_then_empty_finding(db, monkeypatch) -> None:
    shipment_id = await _seed_shipment(db)
    runner = FakeRunner(["không phải JSON", "vẫn không phải JSON"])
    monkeypatch.setattr(research_service.agent_b, "build_agent_b", lambda: runner)

    finding = await research_service.request_research(shipment_id)

    assert runner.calls == 2  # 1 lần + đúng 1 retry
    assert finding.confidence == "thap"
    assert finding.relevance == "thap"
    async with db() as session:
        rows = (await session.execute(select(ResearchFinding))).scalars().all()
        assert rows == []  # finding rỗng KHÔNG persist (không poison cache 12h)


async def test_retry_succeeds_on_second_attempt(db, monkeypatch) -> None:
    shipment_id = await _seed_shipment(db)
    runner = FakeRunner(["xin lỗi, đây là văn xuôi", VALID_JSON])
    monkeypatch.setattr(research_service.agent_b, "build_agent_b", lambda: runner)

    finding = await research_service.request_research(shipment_id)

    assert runner.calls == 2
    assert finding.event == "Bão nhiệt đới gần eo Luzon"


# --- hard cap 3 trong code wrapper (IC§5.2 — không tin riêng framework) ---


async def test_hard_cap_blocks_fourth_agent_b_run(db, monkeypatch) -> None:
    shipment_id = await _seed_shipment(db)
    builds: list[FakeRunner] = []

    def build() -> FakeRunner:
        runner = FakeRunner(["bad", "bad"])  # never valid → nothing cached
        builds.append(runner)
        return runner

    monkeypatch.setattr(research_service.agent_b, "build_agent_b", build)

    for _ in range(5):
        finding = await research_service.request_research(shipment_id)
        assert finding.confidence == "thap"

    assert len(builds) == 3  # calls 4+5 blocked by wrapper hard cap


async def test_agent_b_runner_configured_with_max_turns_3(monkeypatch) -> None:
    captured: dict = {}

    class FakeAG2Runner:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(agent_b, "AG2Runner", FakeAG2Runner)
    monkeypatch.setattr(agent_b, "build_llm_client", lambda: object())

    agent_b.build_agent_b()

    assert captured["max_turns"] == 3
    tool_names = [name for _, name, _ in captured["tools"]]
    assert tool_names == ["web_search"]


# --- thiếu key: không crash ---


async def test_missing_llm_key_returns_empty_finding(db, monkeypatch) -> None:
    monkeypatch.setattr(settings, "LLM_API_KEY", "")
    shipment_id = await _seed_shipment(db)

    finding = await research_service.request_research(shipment_id)

    assert finding.confidence == "thap"


async def test_web_search_without_key_returns_empty_list(monkeypatch) -> None:
    from app.agents import search_tool

    monkeypatch.setattr(settings, "SEARCH_API_KEY", "")

    assert await search_tool.web_search("bão biển đông") == []


async def test_web_search_maps_integration_error_to_empty_list(monkeypatch) -> None:
    from app.agents import search_tool
    from app.integrations import tavily_client
    from app.integrations.errors import ExternalIntegrationError

    monkeypatch.setattr(settings, "SEARCH_API_KEY", "k")

    async def fail(query: str, *, api_key: str, max_results: int = 5):
        raise ExternalIntegrationError("tavily HTTP 500", retryable=True)

    monkeypatch.setattr(tavily_client, "search", fail)

    assert await search_tool.web_search("bão biển đông") == []


# --- API IC§3.2: GET /research-findings + POST /{id}/verify ---


@pytest.fixture
async def client(db, auth_override):
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_session
    from app.main import app

    async def override_session():
        async with db() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def _seed_user(factory) -> int:
    async with factory() as session:
        user = User(email="ops@example.com", provider="google", provider_sub="sub-1")
        session.add(user)
        await session.commit()
        return user.id


async def test_get_research_findings_filters_by_route_key(db, client) -> None:
    shipment_id = await _seed_shipment(db)
    await _seed_finding(db, shipment_id, route_key="SGSIN-VNCLI", event="A")
    await _seed_finding(db, shipment_id, route_key="HKHKG-VNCLI", event="B")

    r = await client.get("/api/v1/research-findings", params={"route_key": "SGSIN-VNCLI"})

    assert r.status_code == 200
    events = [f["event"] for f in r.json()]
    assert events == ["A"]


async def test_get_research_findings_filters_by_shipment_id(db, client) -> None:
    first = await _seed_shipment(db, _shipment("BL-R1"))
    second = await _seed_shipment(db, _shipment("BL-R2"))
    await _seed_finding(db, first, event="A")
    await _seed_finding(db, second, event="B")

    r = await client.get("/api/v1/research-findings", params={"shipment_id": second})

    assert r.status_code == 200
    assert [f["event"] for f in r.json()] == ["B"]


async def test_verify_endpoint_sets_verified_and_verified_by(db, client) -> None:
    user_id = await _seed_user(db)
    shipment_id = await _seed_shipment(db)
    finding_id = await _seed_finding(db, shipment_id)

    r = await client.post(f"/api/v1/research-findings/{finding_id}/verify")

    assert r.status_code == 200
    assert r.json()["event"] == "cached: tắc cảng Cát Lái"
    async with db() as session:
        row = await session.get(ResearchFinding, finding_id)
        assert row.verified is True
        assert row.verified_by == user_id


async def test_verify_unknown_finding_returns_404(db, client) -> None:
    r = await client.post("/api/v1/research-findings/9999/verify")

    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "FINDING_NOT_FOUND"
