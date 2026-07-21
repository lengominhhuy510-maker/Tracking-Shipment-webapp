"""Agent A — ETA Reasoning Agent (Spec §6.3b, §6.4; IC§5.1/5.3) — TASK-08.

Coordinates the 4 tools and synthesizes a qualitative expert assessment.
"Con số do rule quyết, lời do agent nói": the ETA numbers come from the rule
engine; the agent only explains and flags risk. Framework access goes through
``AG2Runner`` — no ``autogen`` import here.
"""

from app.agents import tools
from app.integrations.ag2_runner import AG2Runner
from app.integrations.llm_client import build_llm_client

SYSTEM_PROMPT = """Bạn là Agent A — chuyên gia phân tích ETA cho lô hàng đường biển.

Nhiệm vụ mỗi lần chạy (stateless — không có lịch sử cũ):
1. Gọi get_shipment_state để nắm trạng thái mới nhất của lô hàng.
2. Gọi recompute_eta để lấy breakdown ETA từ rule engine (tier 1/2, factors, deviation).
3. Gọi get_tide_window để biết ETA có rơi vào cửa sổ con nước hay không.
4. Nếu thấy cần bối cảnh tuyến đường, gọi request_research (tối đa 1 lần).

Nguyên tắc BẮT BUỘC:
- Con số ETA do rule engine quyết — bạn KHÔNG được tự tính hay đề xuất ghi đè con số.
- Bạn chỉ diễn giải: vì sao ETA ra như vậy (factors_applied, skipped_reason, deviation),
  rủi ro con nước, và bối cảnh tuyến.
- Mọi thông tin từ request_research phải gắn nhãn "cần xác minh".
- Nếu dữ liệu thiếu (skipped_reason, tide data cũ), nêu rõ giới hạn đó.

Kết thúc: trả về MỘT đoạn nhận định chuyên gia tiếng Việt ngắn gọn (3-6 câu),
rồi viết TERMINATE trên dòng cuối."""

_TOOLS = [
    (
        tools.get_shipment_state,
        "get_shipment_state",
        "Nạp state mới nhất của lô hàng từ DB: vị trí, SOG/COG, ETA, ATD, status, "
        "env_conditions, route_key.",
    ),
    (
        tools.recompute_eta,
        "recompute_eta",
        "Chạy ETA Engine tầng 1+2 (thuần code) và trả breakdown: eta_tier1/tier2, "
        "avg_sog_kn, distance_remaining_nm, factors_applied, skipped_reason, deviation_pct.",
    ),
    (
        tools.get_tide_window,
        "get_tide_window",
        "Đọc dữ liệu thủy triều đã cache (env_conditions): extremes, "
        "eta_falls_in_window, station_name, data_age_hours.",
    ),
    (
        tools.request_research,
        "request_research",
        "Yêu cầu research bối cảnh tuyến đường (Agent B). focus = hướng search cụ thể. "
        "Kết quả luôn cần xác minh.",
    ),
]


def build_agent_a() -> AG2Runner:
    """Build a fresh Agent A runner (raises ExternalIntegrationError sans key)."""
    return AG2Runner(
        name="agent_a",
        system_message=SYSTEM_PROMPT,
        llm_client=build_llm_client(),
        tools=_TOOLS,
        max_turns=3,
    )


def analysis_message(shipment_id: int) -> str:
    return (
        f"Phân tích ETA cho lô hàng shipment_id={shipment_id}. "
        "Dùng các tool để lấy dữ liệu rồi đưa nhận định chuyên gia."
    )
