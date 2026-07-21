"""LLM transport boundary (Decision 0005, §3.4) — OpenAI-compatible via env.

Isolates LLM endpoint config so domain code never touches api keys or the AG2
``LLMConfig`` shape directly. No business logic here.
"""

from dataclasses import dataclass

from app.config import settings
from app.integrations.errors import ExternalIntegrationError


@dataclass(frozen=True)
class LLMClient:
    """Validated OpenAI-compatible endpoint config (IC§7 env vars)."""

    base_url: str
    api_key: str
    model: str

    def as_config_entry(self) -> dict:
        """One AG2 ``LLMConfig`` dict entry (api_type openai, spike_ag2 pattern)."""
        entry = {"api_type": "openai", "model": self.model, "api_key": self.api_key}
        if self.base_url:
            entry["base_url"] = self.base_url
        return entry


def build_llm_client() -> LLMClient:
    """Read settings; raise non-retryable when the key/model are missing."""
    api_key = settings.LLM_API_KEY.strip()
    model = settings.LLM_MODEL.strip()
    if not (api_key and model):
        raise ExternalIntegrationError(
            "thiếu LLM_API_KEY/LLM_MODEL — điền vào .env để chạy Agent A",
            retryable=False,
        )
    return LLMClient(base_url=settings.LLM_BASE_URL.strip(), api_key=api_key, model=model)
