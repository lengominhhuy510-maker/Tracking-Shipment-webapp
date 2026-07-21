"""AG2 framework boundary (Decision 0005) — the ONLY runtime module besides
``llm_client`` allowed to import ``autogen`` (package ``ag2==0.14.0``).

Wraps agent construction + tool registration + one async chat run. Verified
against the pinned 0.14.0 docstrings (spike_ag2.py gate): ``register_function``
accepts async callables; ``a_initiate_chat`` returns ``ChatResult`` with
``.summary``/``.chat_history``. Any framework/SDK exception maps to
``ExternalIntegrationError`` — no AG2 types leak out of this file.
"""

import logging
from collections.abc import Callable

from autogen import ConversableAgent, LLMConfig, register_function

from app.integrations.errors import ExternalIntegrationError
from app.integrations.llm_client import LLMClient

logger = logging.getLogger(__name__)

TERMINATE_MARKER = "TERMINATE"


class AG2Runner:
    """One stateless assistant/executor pair with registered function tools."""

    def __init__(
        self,
        *,
        name: str,
        system_message: str,
        llm_client: LLMClient,
        tools: list[tuple[Callable, str, str]],
        max_turns: int = 3,
    ) -> None:
        self._max_turns = max_turns
        try:
            llm_config = LLMConfig(llm_client.as_config_entry())
            self._assistant = ConversableAgent(
                name=name,
                system_message=system_message,
                human_input_mode="NEVER",
                llm_config=llm_config,
            )
            self._executor = ConversableAgent(
                name=f"{name}_executor",
                human_input_mode="NEVER",
                llm_config=False,
                is_termination_msg=lambda msg: TERMINATE_MARKER in (msg.get("content") or ""),
            )
            for fn, tool_name, description in tools:
                register_function(
                    fn,
                    caller=self._assistant,
                    executor=self._executor,
                    name=tool_name,
                    description=description,
                )
        except Exception as exc:  # framework construction failed — config problem
            raise ExternalIntegrationError(
                f"AG2 agent setup failed: {exc}", retryable=False
            ) from exc

    async def run(self, message: str) -> str:
        """Run one A-chat (§6.4 stateless — fresh history) and return the
        assistant's final assessment text."""
        try:
            result = await self._executor.a_initiate_chat(
                self._assistant,
                message=message,
                max_turns=self._max_turns,
                clear_history=True,
            )
        except Exception as exc:
            raise ExternalIntegrationError(
                f"AG2 chat run failed: {exc}", retryable=True
            ) from exc

        summary = (result.summary or "").strip() if result.summary else ""
        if not summary:
            # Fall back to the last non-empty assistant message.
            for msg in reversed(result.chat_history or []):
                content = (msg.get("content") or "").strip()
                if content:
                    summary = content
                    break
        return summary.replace(TERMINATE_MARKER, "").strip()
