"""Unit tests for the LLM provider layer.

Tests cover:
- MockProvider produces correct LLMResponse for success and insufficient-evidence cases
- Factory selects MockProvider by default / when LLM_PROVIDER=mock
- Factory raises on unknown provider
- AnthropicProvider / OpenAIProvider are NOT tested here (require live API keys).
  Integration tests for those live in tests/integration/ (excluded from CI).
"""

from __future__ import annotations

import pytest

from apps.worker.agent.providers.base import LLMProvider, LLMResponse
from apps.worker.agent.providers.factory import build_provider
from apps.worker.agent.providers.mock import MockProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(provider: str = "mock", model: str = "mock-model"):  # type: ignore[return]
    """Return a minimal Settings-like object for the factory."""

    class _FakeSettings:
        llm_provider = provider
        llm_model = model
        llm_api_key = ""
        llm_base_url = ""
        llm_timeout_seconds = 5.0
        anthropic_api_key = ""
        openai_api_key = ""

    return _FakeSettings()


EVIDENCE_DEPLOY = {
    "id": "aaa00000-0000-0000-0000-000000000001",
    "source_type": "deployment",
    "summary": "v1.4.2 deployed by ci-bot",
    "raw_data": {"commit": "abc"},
}
EVIDENCE_METRIC = {
    "id": "bbb00000-0000-0000-0000-000000000002",
    "source_type": "metric",
    "summary": "error rate rose to 35%",
    "raw_data": {},
}
EVIDENCE_LOG = {
    "id": "ccc00000-0000-0000-0000-000000000003",
    "source_type": "log",
    "summary": "database connection timeout after 5000ms",
    "raw_data": {},
}

GOOD_SIGNALS = {
    "has_deployment": True,
    "has_error_logs": True,
    "has_metric_anomaly": True,
    "is_connection_exhaustion": True,
}

BAD_SIGNALS_NO_DEPLOYMENT = {
    "has_deployment": False,
    "has_error_logs": True,
    "has_metric_anomaly": True,
}


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


def test_factory_returns_mock_by_default() -> None:
    settings = _make_settings(provider="mock")
    provider = build_provider(settings)  # type: ignore[arg-type]
    assert isinstance(provider, MockProvider)
    assert provider.name == "mock"


def test_factory_returns_mock_for_empty_provider() -> None:
    settings = _make_settings(provider="")
    provider = build_provider(settings)  # type: ignore[arg-type]
    assert isinstance(provider, MockProvider)


def test_factory_raises_for_unknown_provider() -> None:
    settings = _make_settings(provider="grok-llm")
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        build_provider(settings)  # type: ignore[arg-type]


def test_factory_anthropic_raises_without_api_key() -> None:
    settings = _make_settings(provider="anthropic")
    # No key set — should raise ValueError before even importing anthropic SDK
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_provider(settings)  # type: ignore[arg-type]


def test_factory_openai_raises_without_api_key() -> None:
    settings = _make_settings(provider="openai")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_provider(settings)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# MockProvider unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_provider_success_case() -> None:
    provider = MockProvider()
    response = await provider.generate_hypothesis(
        incident_id="inc-001",
        service_name="checkout-api",
        alert_type="high_error_rate",
        severity="critical",
        evidence_records=[EVIDENCE_DEPLOY, EVIDENCE_METRIC, EVIDENCE_LOG],
        retrieved_runbooks=[{"title": "Checkout DB Connection Exhaustion"}],
        signals=GOOD_SIGNALS,
        min_confidence=0.6,
        prompt_version="incident-analysis-v1",
    )

    assert isinstance(response, LLMResponse)
    assert response.is_mock is True
    assert response.root_cause == "deployment_regression"
    assert response.hypothesis_summary is not None
    assert response.confidence >= 0.6
    # All cited IDs must come from the provided evidence records
    provided_ids = {EVIDENCE_DEPLOY["id"], EVIDENCE_METRIC["id"], EVIDENCE_LOG["id"]}
    assert set(response.cited_evidence_ids).issubset(provided_ids)
    assert response.action_type == "simulated_rollback"
    assert response.action_parameters.get("incident_id") == "inc-001"
    assert "Checkout DB Connection Exhaustion" in (response.action_rationale or "")


@pytest.mark.asyncio
async def test_mock_provider_insufficient_no_deployment() -> None:
    provider = MockProvider()
    response = await provider.generate_hypothesis(
        incident_id="inc-002",
        service_name="payment-api",
        alert_type="latency_spike",
        severity="high",
        evidence_records=[EVIDENCE_METRIC],
        retrieved_runbooks=[],
        signals=BAD_SIGNALS_NO_DEPLOYMENT,
        min_confidence=0.6,
        prompt_version="incident-analysis-v1",
    )

    assert response.root_cause is None
    assert response.hypothesis_summary is None
    assert response.confidence == 0.0
    assert response.is_mock is True


@pytest.mark.asyncio
async def test_mock_provider_insufficient_below_min_confidence() -> None:
    provider = MockProvider()
    response = await provider.generate_hypothesis(
        incident_id="inc-003",
        service_name="checkout-api",
        alert_type="high_error_rate",
        severity="critical",
        evidence_records=[EVIDENCE_DEPLOY, EVIDENCE_METRIC],
        retrieved_runbooks=[],
        signals=GOOD_SIGNALS,
        min_confidence=0.99,  # impossible to reach
        prompt_version="incident-analysis-v1",
    )

    assert response.root_cause is None
    assert response.hypothesis_summary is None
    assert response.is_mock is True


@pytest.mark.asyncio
async def test_mock_provider_high_latency_variant() -> None:
    provider = MockProvider()
    latency_signals = {
        "has_deployment": True,
        "has_metric_anomaly": True,
        "has_error_logs": False,
        "is_connection_exhaustion": False,
        "is_high_latency": True,
    }
    response = await provider.generate_hypothesis(
        incident_id="inc-004",
        service_name="checkout-api",
        alert_type="latency_spike",
        severity="high",
        evidence_records=[EVIDENCE_DEPLOY, EVIDENCE_METRIC],
        retrieved_runbooks=[],
        signals=latency_signals,
        min_confidence=0.6,
        prompt_version="incident-analysis-v1",
    )

    assert response.root_cause == "deployment_regression"
    assert "latency" in (response.hypothesis_summary or "").lower()


# ---------------------------------------------------------------------------
# LLMProvider ABC enforcement
# ---------------------------------------------------------------------------


def test_llm_provider_is_abstract() -> None:
    """LLMProvider cannot be instantiated without implementing abstract methods."""
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]
