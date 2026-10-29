"""Abstract base class for LLM providers.

The agent uses this interface exclusively — no provider SDK leaks into node logic.

Design contract:
- LLM only receives evidence; it returns hypothesis + reasoning + recommendation.
- Backend deterministic checks (evidence ID validation, allowlist, confidence
  threshold, human approval) run AFTER the LLM call, independent of the LLM.
- Provider is stateless; each call is self-contained.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    """Structured output returned by every provider.

    The LLM is *never* allowed to bypass backend validation — it can only propose.
    The backend deterministically decides whether the proposal is safe to forward.
    """

    # Free-text reasoning chain (Evidence → Hypothesis → Reasoning → Recommendation)
    reasoning: str

    # Structured outputs (may be None if the LLM concludes insufficient evidence)
    root_cause: str | None
    hypothesis_summary: str | None
    confidence: float  # 0.0 – 1.0

    # Evidence IDs the LLM cited.  Backend will validate every ID.
    cited_evidence_ids: list[str] = field(default_factory=list)

    # Proposed remediation (backend will allowlist-check the action_type)
    action_type: str | None = None
    action_parameters: dict[str, Any] = field(default_factory=dict)
    action_rationale: str | None = None

    # Token usage for audit
    input_tokens: int = 0
    output_tokens: int = 0

    # Fallback flag — True when the provider was not available
    is_mock: bool = False


class LLMProvider(abc.ABC):
    """Contract every LLM backend must satisfy."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable provider identifier, e.g. 'anthropic', 'openai', 'mock'."""

    @abc.abstractmethod
    async def generate_hypothesis(
        self,
        *,
        incident_id: str,
        service_name: str,
        alert_type: str,
        severity: str,
        evidence_records: list[dict[str, Any]],
        retrieved_runbooks: list[dict[str, Any]],
        signals: dict[str, Any],
        min_confidence: float,
        prompt_version: str,
    ) -> LLMResponse:
        """Ask the LLM to reason over evidence and propose a hypothesis.

        The LLM MUST:
        1. Only cite evidence IDs that appear in ``evidence_records``.
        2. Produce a confidence value between 0.0 and 1.0.
        3. Propose an action_type from the allow-list (or None).

        The backend will independently verify all three invariants.
        """
