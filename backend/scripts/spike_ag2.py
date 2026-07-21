"""Spike/compatibility gate: AG2 (package ``ag2==0.14.0``, import name ``autogen``).

Chạy từ ``backend/``:  python scripts/spike_ag2.py

Dựng 1 ConversableAgent gọi 1 tool Python đơn giản qua register_function,
in kết quả rồi thoát. CẦN LLM key (SMOKE-KEY GATE): đọc ``LLM_BASE_URL`` /
``LLM_API_KEY`` / ``LLM_MODEL`` từ env (IC§7). Thiếu key -> PASS cấu trúc
(import + dựng agent + đăng ký tool OK), in hướng dẫn smoke lại, exit 0.
"""

import os
import sys

from autogen import ConversableAgent, LLMConfig, register_function

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252


def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the sum."""
    return a + b


def build_agents(llm_config: LLMConfig):
    assistant = ConversableAgent(
        name="spike_assistant",
        system_message=(
            "You are a calculator assistant. Use the add_numbers tool to compute sums. "
            "Reply TERMINATE after reporting the result."
        ),
        human_input_mode="NEVER",
        llm_config=llm_config,
    )
    executor = ConversableAgent(
        name="spike_executor",
        human_input_mode="NEVER",
        llm_config=False,
        is_termination_msg=lambda msg: "TERMINATE" in (msg.get("content") or ""),
    )
    register_function(
        add_numbers,
        caller=assistant,
        executor=executor,
        name="add_numbers",
        description="Add two integers a and b.",
    )
    return assistant, executor


def main() -> int:
    base_url = os.environ.get("LLM_BASE_URL", "").strip()
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    model = os.environ.get("LLM_MODEL", "").strip()

    if not (api_key and model):
        # PASS cấu trúc: registration cần llm_config -> dùng placeholder, KHÔNG gọi mạng
        placeholder = LLMConfig(
            {"api_type": "openai", "model": "placeholder-model", "api_key": "placeholder"}
        )
        assistant, executor = build_agents(placeholder)
        print(f"agents built: {assistant.name}, {executor.name}")
        print(f"tool map on executor: {list(executor.function_map)}")
        assert "add_numbers" in executor.function_map
        tool_names = [
            t["function"]["name"] for t in (assistant.llm_config.tools or [])
        ]
        print(f"tool schema on assistant llm_config: {tool_names}")
        assert "add_numbers" in tool_names
        print("PASS cấu trúc (ag2==0.14.0 import/agent/tool OK)")
        print("cần smoke lại: TASK-01 spike_ag2 (LLM key) — điền LLM_API_KEY/LLM_MODEL vào .env")
        return 0

    entry = {"api_type": "openai", "model": model, "api_key": api_key}
    if base_url:
        entry["base_url"] = base_url
    llm_config = LLMConfig(entry)

    assistant, executor = build_agents(llm_config)
    result = executor.initiate_chat(
        assistant,
        message="What is 21754 + 87621? Use the add_numbers tool.",
        max_turns=3,
    )
    print("--- chat summary ---")
    print(result.summary)
    expected = str(add_numbers(21754, 87621))
    history_text = " ".join(str(m.get("content")) for m in result.chat_history)
    if expected in history_text:
        print(f"tool result {expected} xuất hiện trong hội thoại — AG2 tool call OK")
    else:
        print("cảnh báo: không thấy kết quả tool trong hội thoại — xem transcript phía trên")
    return 0


if __name__ == "__main__":
    sys.exit(main())
