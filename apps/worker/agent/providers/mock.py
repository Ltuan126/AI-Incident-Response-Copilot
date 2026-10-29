"""MockProvider — zero-dependency provider for local dev, CI, and CV demo.

Switch via environment variable:
    LLM_PROVIDER=mock

Behaviour:
- Replicates the exact reasoning chain the real providers would perform.
- Returns deterministic, realistic outputs without any API key or network call.
- Marked with is_mock=True so callers can log this for transparency.
"""

from __future__ import annotations

import json
from typing import Any

from apps.worker.agent.providers.base import LLMProvider, LLMResponse

_ALLOWED_ACTIONS = frozenset(
    {"simulated_restart", "simulated_rollback", "simulated_scale", "create_incident_note"}
)

# Simulated reasoning template — mirrors the structure a real LLM prompt would produce.
_REASONING_TEMPLATE = """\
## Evidence Review
{evidence_summary}

## Runbook Cross-Reference
{runbook_summary}

## Signals
{signals_summary}

## Hypothesis
Root cause: {root_cause}
Confidence: {confidence:.0%}
Cited evidence IDs: {cited_ids}

## Reasoning
{reasoning_text}

## Recommendation
Action: {action_type}
Rationale: {rationale}
Requires human approval: true
"""


class MockProvider(LLMProvider):
    """Deterministic mock that produces human-readable reasoning without any LLM call."""

    @property
    def name(self) -> str:
        return "mock"

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
        has_deployment = signals.get("has_deployment", False)
        has_degradation = signals.get("has_metric_anomaly", False) or signals.get(
            "has_error_logs", False
        )

        # Gather cited evidence IDs (all records that exist)
        cited_ids = [str(e["id"]) for e in evidence_records if e.get("id")]

        if not (has_deployment and has_degradation) or len(cited_ids) < 2:
            return LLMResponse(
                reasoning=(
                    "Evidence review did not surface both a deployment event and a "
                    "corresponding degradation signal.  Concluding insufficient evidence."
                ),
                root_cause=None,
                hypothesis_summary=None,
                confidence=0.0,
                cited_evidence_ids=cited_ids,
                is_mock=True,
            )

        confidence = min(0.95, 0.55 + 0.1 * min(len(cited_ids), 4))
        if confidence < min_confidence:
            return LLMResponse(
                reasoning=(
                    f"Computed confidence {confidence:.0%} is below the requested threshold "
                    f"{min_confidence:.0%}.  Declining to propose a hypothesis."
                ),
                root_cause=None,
                hypothesis_summary=None,
                confidence=confidence,
                cited_evidence_ids=cited_ids,
                is_mock=True,
            )

        # Choose hypothesis flavour based on signals
        if signals.get("is_connection_exhaustion"):
            root_cause = "deployment_regression"
            hypothesis_summary = (
                f"A recent deployment to {service_name} introduced database connection "
                "exhaustion, leading to timeouts and elevated error rates as documented "
                "in the service runbook."
            )
            reasoning_text = (
                "The deployment event temporally precedes the connection exhaustion "
                "pattern.  Log evidence shows timeout errors; metrics confirm rising "
                "5xx rates.  Runbook recommends rollback as the primary mitigation."
            )
        elif signals.get("is_high_latency"):
            root_cause = "deployment_regression"
            hypothesis_summary = (
                f"A recent deployment to {service_name} caused latency degradation "
                "without 5xx errors, consistent with increased synchronous processing time."
            )
            reasoning_text = (
                "Latency metrics spiked after the deployment but error logs are absent, "
                "suggesting a slow code path rather than a hard failure.  "
                "Rollback is the safest recovery action pending profiling."
            )
        else:
            root_cause = "deployment_regression"
            hypothesis_summary = (
                f"A recent deployment to {service_name} is the most likely cause of "
                "the incident: deployment evidence aligns with metric or log degradation."
            )
            reasoning_text = (
                "Correlated deployment and degradation signals are present.  "
                "Without a more specific failure signature the safest remediation "
                "is a controlled rollback pending human review."
            )

        action_type = "simulated_rollback"
        runbook_title = (
            retrieved_runbooks[0].get("title", "standard runbook")
            if retrieved_runbooks
            else "standard runbook"
        )
        rationale = (
            f"Roll back the implicated deployment after human approval, "
            f"then verify recovery in accordance with '{runbook_title}'."
        )

        evidence_summary = "\n".join(
            f"  [{e.get('source_type', '?')}] {e.get('summary', '')[:80]}"
            for e in evidence_records
        )
        runbook_summary = "\n".join(
            f"  - {rb.get('title', '?')}" for rb in retrieved_runbooks
        ) or "  (none retrieved)"
        signals_text = json.dumps(signals, indent=2)

        reasoning = _REASONING_TEMPLATE.format(
            evidence_summary=evidence_summary,
            runbook_summary=runbook_summary,
            signals_summary=signals_text,
            root_cause=root_cause,
            confidence=confidence,
            cited_ids=", ".join(cited_ids),
            reasoning_text=reasoning_text,
            action_type=action_type,
            rationale=rationale,
        )

        return LLMResponse(
            reasoning=reasoning,
            root_cause=root_cause,
            hypothesis_summary=hypothesis_summary,
            confidence=confidence,
            cited_evidence_ids=cited_ids,
            action_type=action_type,
            action_parameters={"incident_id": incident_id},
            action_rationale=rationale,
            input_tokens=0,
            output_tokens=0,
            is_mock=True,
        )
