"""Agent B — Research Agent (Spec §6.3c, IC§5.2) — TASK-09.

One AG2 agent with exactly one tool (``web_search``). Returns a JSON string the
wrapper validates against ``ResearchFindingOut`` (JSON mode + 1 retry lives in
``research_service``, not here). Framework access goes through ``AG2Runner``.
"""

from app.agents import search_tool
from app.integrations.ag2_runner import AG2Runner
from app.integrations.llm_client import build_llm_client

SYSTEM_PROMPT = """Bạn là Agent B — research agent cho tuyến vận tải biển.

Nhiệm vụ: tìm sự kiện ảnh hưởng tuyến/ETA — bão, xung đột khu vực, tắc nghẽn
cảng, sự cố kênh đào/eo biển. Dùng tool web_search (tối đa 3 lần); tự đánh giá
tin có thật sự liên quan tuyến + khung thời gian ETA không, chưa chắc thì search
lại với từ khóa khác.

Kết quả trả về: CHỈ MỘT object JSON hợp lệ, không markdown, không văn xuôi,
đúng schema:
{"event": str, "relevance": "cao"|"trung_binh"|"thap",
 "route_impact": str, "confidence": "cao"|"trung_binh"|"thap",
 "sources": [url, ...]}  # >=1 URL từ kết quả search

Nếu không tìm thấy gì liên quan: event mô tả "không phát hiện sự kiện đáng kể",
relevance="thap", confidence="thap", sources = URL đã kiểm tra.
Sau object JSON, viết TERMINATE trên dòng cuối."""

_TOOLS = [
    (
        search_tool.web_search,
        "web_search",
        "Tìm tin tức/sự kiện hàng hải theo từ khóa. Trả list {title, url, content, score}.",
    ),
]


def build_agent_b() -> AG2Runner:
    """Build a fresh Agent B runner (raises ExternalIntegrationError sans key)."""
    return AG2Runner(
        name="agent_b",
        system_message=SYSTEM_PROMPT,
        llm_client=build_llm_client(),
        tools=_TOOLS,
        max_turns=3,
    )


def research_message(
    *, pol: str, pod: str, route_key: str | None, eta_current: str | None, focus: str | None
) -> str:
    parts = [
        f"Nghiên cứu tuyến {pol} → {pod}" + (f" (route_key {route_key})" if route_key else "") + "."
    ]
    if eta_current:
        parts.append(f"Khung thời gian ETA hiện tại: {eta_current}.")
    if focus:
        parts.append(f"Hướng search cụ thể: {focus}.")
    parts.append("Trả về đúng một object JSON theo schema đã cho.")
    return " ".join(parts)
