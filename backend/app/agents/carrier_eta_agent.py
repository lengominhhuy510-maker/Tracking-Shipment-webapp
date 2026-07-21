"""Carrier ETA Agent — agentic browser reading carrier tracking sites (§6.7b/§6.7c).

AG2 agent whose browser tools all go through ``BrowserAgentClient`` (the MCP
gateway) — this module NEVER imports the ``mcp`` package. Read-only: it opens
public tracking pages, fills B/L/booking, extracts the published ETA at the
destination port. It never logs in with real credentials (§6.7c).

The agent's final message carries a machine-readable marker::

    ETA_FOUND: 2026-08-01T10:00:00+00:00
    ETA_NOT_FOUND: <reason>

which ``carrier_eta_service`` parses. Framework access goes through
``AG2Runner`` — no ``autogen`` import here either.
"""

import logging

from app.integrations.ag2_runner import AG2Runner
from app.integrations.browser_agent_client import BrowserAgentClient
from app.integrations.llm_client import build_llm_client

logger = logging.getLogger(__name__)

# IC§8 — public tracking pages of the 5 supported carriers (match by substring
# on the shipment's free-text carrier field, normalized lowercase).
CARRIER_TRACKING_URLS = {
    "maersk": "https://www.maersk.com/tracking/",
    "msc": "https://www.msc.com/en/track-a-shipment",
    "one": "https://ecomm.one-line.com/one-ecom/manage-shipment/cargo-tracking",
    "wan hai": "https://www.wanhai.com/views/cargoTrack/CargoTrack.xhtml",
    "evergreen": "https://www.shipmentlink.com/servlet/TDB1_CargoTracking.do",
}

SYSTEM_PROMPT = """Bạn là Carrier ETA Agent — đọc trang tracking CÔNG KHAI của hãng tàu \
để trích ETA cập cảng đích cho một lô hàng.

Công cụ trình duyệt: browser_navigate (mở URL), browser_snapshot (đọc \
accessibility snapshot trang hiện tại), browser_click (click element theo ref \
từ snapshot), browser_type (gõ text vào element theo ref, submit được).

Quy trình gợi ý (layout mỗi hãng khác nhau — bạn tự quyết):
1. Mở URL tracking của hãng (đã cho trong yêu cầu).
2. Snapshot trang, tìm ô nhập số B/L / booking / container.
3. Điền số và submit, snapshot kết quả.
4. Tìm ETA (Estimated Time of Arrival) tại cảng đích trong bảng lịch trình.

Nguyên tắc BẮT BUỘC:
- CHỈ ĐỌC trang công khai. TUYỆT ĐỐI KHÔNG đăng nhập, không điền username/\
password, không tạo tài khoản. Gặp trang bắt đăng nhập hoặc captcha → dừng, \
báo không lấy được.
- Không điền form nào ngoài ô tra cứu tracking.
- Tối đa vài lượt thao tác — không loay hoay vô hạn.

Kết thúc, dòng ÁP CHÓT phải là đúng MỘT trong hai marker:
ETA_FOUND: <datetime ISO-8601 kèm timezone, ví dụ 2026-08-01T10:00:00+00:00>
ETA_NOT_FOUND: <lý do ngắn: captcha / login_required / layout / not_found / khác>

rồi viết TERMINATE trên dòng cuối."""


def _tracking_url(carrier: str) -> str | None:
    needle = (carrier or "").strip().lower()
    if not needle:
        return None
    for key, url in CARRIER_TRACKING_URLS.items():
        if key in needle:
            return url
    return None


async def run_carrier_eta_agent(
    *,
    carrier: str,
    bl_number: str | None,
    container_no: str | None,
    pod: str | None,
) -> str:
    """Run one agent session; return the final assistant text (with marker).

    Raises ``ExternalIntegrationError`` when MCP/LLM/framework fail — the
    caller (service) is responsible for swallowing it (non-blocking).
    """
    url = _tracking_url(carrier)
    if url is None:
        return f"ETA_NOT_FOUND: carrier không hỗ trợ ({carrier!r})"

    async with BrowserAgentClient() as browser:

        async def browser_navigate(target_url: str) -> str:
            return await browser.call_tool("browser_navigate", {"url": target_url})

        async def browser_snapshot() -> str:
            return await browser.call_tool("browser_snapshot", {})

        async def browser_click(element: str, ref: str) -> str:
            return await browser.call_tool(
                "browser_click", {"element": element, "ref": ref}
            )

        async def browser_type(element: str, ref: str, text: str, submit: bool) -> str:
            return await browser.call_tool(
                "browser_type",
                {"element": element, "ref": ref, "text": text, "submit": submit},
            )

        runner = AG2Runner(
            name="carrier_eta_agent",
            system_message=SYSTEM_PROMPT,
            llm_client=build_llm_client(),
            tools=[
                (browser_navigate, "browser_navigate", "Mở một URL trong trình duyệt."),
                (
                    browser_snapshot,
                    "browser_snapshot",
                    "Đọc accessibility snapshot của trang hiện tại (element + ref).",
                ),
                (
                    browser_click,
                    "browser_click",
                    "Click element theo mô tả + ref lấy từ snapshot.",
                ),
                (
                    browser_type,
                    "browser_type",
                    "Gõ text vào element theo ref; submit=true để Enter.",
                ),
            ],
            max_turns=10,
        )
        reference = bl_number or container_no or ""
        return await runner.run(
            f"Tra ETA cho lô hàng: hãng {carrier}, số B/L/booking '{reference}', "
            f"container '{container_no or ''}', cảng đích (POD) '{pod or ''}'. "
            f"URL tracking của hãng: {url}. "
            "Trích ETA cập cảng đích và kết thúc bằng marker ETA_FOUND/ETA_NOT_FOUND."
        )
