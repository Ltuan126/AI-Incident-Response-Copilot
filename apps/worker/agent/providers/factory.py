"""Provider factory — reads LLM_PROVIDER from settings and returns the right adapter.

Usage in nodes:
    from apps.worker.agent.providers import build_provider
    provider = build_provider(settings)
    response = await provider.generate_hypothesis(...)

Local dev / CI:
    LLM_PROVIDER=mock        # no API key needed

Demo:
    LLM_PROVIDER=anthropic   ANTHROPIC_API_KEY=sk-ant-...
    LLM_PROVIDER=openai      OPENAI_API_KEY=sk-...
"""

from __future__ import annotations

from apps.api.app.core.config import Settings
from apps.api.app.core.logging import get_logger
from apps.worker.agent.providers.base import LLMProvider

logger = get_logger(__name__)


def build_provider(settings: Settings) -> LLMProvider:
    """Instantiate the correct LLMProvider based on ``LLM_PROVIDER`` env var."""
    provider_name = settings.llm_provider.lower().strip()

    if provider_name == "mock" or not provider_name:
        from apps.worker.agent.providers.mock import MockProvider

        logger.info("llm_provider_selected", provider="mock")
        return MockProvider()

    if provider_name == "anthropic":
        from apps.worker.agent.providers.anthropic import AnthropicProvider

        api_key = settings.anthropic_api_key or settings.llm_api_key
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY (or LLM_API_KEY) must be set when LLM_PROVIDER=anthropic"
            )
        logger.info("llm_provider_selected", provider="anthropic", model=settings.llm_model)
        return AnthropicProvider(
            api_key=api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout_seconds,
        )

    if provider_name == "openai":
        from apps.worker.agent.providers.openai import OpenAIProvider

        api_key = settings.openai_api_key or settings.llm_api_key
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY (or LLM_API_KEY) must be set when LLM_PROVIDER=openai"
            )
        logger.info("llm_provider_selected", provider="openai", model=settings.llm_model)
        return OpenAIProvider(
            api_key=api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout_seconds,
            base_url=settings.llm_base_url,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider_name}'. "
        "Supported values: mock, anthropic, openai"
    )
