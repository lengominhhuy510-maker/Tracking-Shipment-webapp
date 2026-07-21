"""Email Agent extraction layer (§7.1, IC§4.2) — LLM → ``EmailExtraction``.

LLM access goes through ``LLMClient``/``AG2Runner`` (Decision 0005) — no
``autogen``/SDK import here. JSON mode by prompt contract + Pydantic validation
+ exactly ONE retry (the retry prompt carries the validation error). A second
failure raises ``EmailParseError`` which the service maps to the
``parse_failed`` outcome — the app never crashes on a bad mail.

The prompt instructs the model to parse through quoted/forwarded layers (§7.4
true-forward) so manually-forwarded carrier mails extract the original data.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.integrations.ag2_runner import AG2Runner
from app.integrations.llm_client import build_llm_client

logger = logging.getLogger(__name__)


class EmailParseError(Exception):
    """LLM output could not be parsed/validated after the single retry."""


class EmailExtraction(BaseModel):
    """IC§4.2 — LLM output shape. ``extracted_json`` stores this verbatim."""

    containers: list[str] = Field(min_length=1)
    from_voyage: str | None = None
    to_voyage: str | None = None
    new_eta: datetime | None = None
    new_vessel_name: str | None = None
    reason: str
    email_type: Literal["rollover", "vessel_change", "transit_delay", "other"]

    @field_validator("new_eta")
    @classmethod
    def _assume_utc(cls, value: datetime | None) -> datetime | None:
        # Carrier mails may quote local time without offset — treat as UTC (IC§15).
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC) if value is not None else None


SYSTEM_PROMPT = """Bạn là Email Extraction Agent — trích xuất dữ liệu vận tải biển \
từ email hãng tàu/forwarder.

Email có thể là forward (Fwd:, quoted, "---------- Forwarded message ----------"): \
khi đó PHẢI đọc xuyên qua lớp forward để lấy dữ liệu của email GỐC bên trong.

Trả về DUY NHẤT một JSON object (không markdown, không giải thích) đúng schema:
{
  "containers": [<mã container, ví dụ "MSKU1234565" — mail có thể nhắc NHIỀU container>],
  "from_voyage": <chuyến cũ hoặc null>,
  "to_voyage": <chuyến mới hoặc null>,
  "new_eta": <ETA mới ISO-8601 kèm timezone, ví dụ "2026-08-10T14:00:00+00:00", hoặc null>,
  "new_vessel_name": <TÊN TÀU MỚI nếu mail báo đổi tàu/rollover, ngược lại null>,
  "reason": <lý do ngắn gọn trích từ mail>,
  "email_type": <"rollover" | "vessel_change" | "transit_delay" | "other">
}

Nguyên tắc:
- "containers" ít nhất 1 phần tử; liệt kê ĐỦ mọi container trong mail.
- "new_vessel_name" CHỈ điền khi mail nêu rõ tàu mới (rollover/vessel change).
- Không bịa dữ liệu không có trong mail — thiếu thì để null.

Sau JSON, viết TERMINATE trên dòng cuối."""

RunLLM = Callable[[str], Awaitable[str]]


async def _run_llm_default(message: str) -> str:
    runner = AG2Runner(
        name="email_agent",
        system_message=SYSTEM_PROMPT,
        llm_client=build_llm_client(),
        tools=[],
        max_turns=1,
    )
    return await runner.run(message)


def _parse_extraction(text: str) -> EmailExtraction:
    """Pull the first JSON object out of the reply and validate it."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise EmailParseError(f"không thấy JSON object trong output: {text[:200]!r}")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise EmailParseError(f"JSON không hợp lệ: {exc}") from exc
    try:
        return EmailExtraction.model_validate(data)
    except ValidationError as exc:
        raise EmailParseError(f"EmailExtraction validation fail: {exc}") from exc


async def extract_email(
    subject: str,
    body: str,
    *,
    run_llm: RunLLM = _run_llm_default,
) -> EmailExtraction:
    """Extract ``EmailExtraction`` from one mail; exactly one retry on bad output."""
    message = f"Trích xuất từ email sau.\n\nSubject: {subject}\n\n{body}"
    try:
        return _parse_extraction(await run_llm(message))
    except EmailParseError as first_error:
        logger.warning("email extract attempt 1 failed, retrying once: %s", first_error)
        retry_message = (
            f"{message}\n\nLần trước output của bạn KHÔNG hợp lệ ({first_error}). "
            "Trả về đúng MỘT JSON object theo schema, không thêm gì khác."
        )
        return _parse_extraction(await run_llm(retry_message))
