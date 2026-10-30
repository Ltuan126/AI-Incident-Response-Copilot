"""LangGraph node: generate structured, evidence-grounded hypotheses via LLM provider.

Design:
    LLM call produces:  Evidence → Hypothesis → Reasoning → Recommendation
    Backend then enforces (in validate_grounding_node):
        1. cited_evidence_ids must exist in collected records (anti-hallucination)
        2. confidence >= min_confidence
    Backend enforces in safety_check_node:
        3. action_type in ALLOWED_ACTIONS
    Backend enforces before execution:
        4. Human approval required (approval_service)

The LLM is intentionally NOT trusted to make final decisions.
It is only trusted to produce a structured proposal for backend review.
"""

from __future__ import annotations

import asyncio
from typing import Any

from apps.api.app.core.config import get_settings
from apps.api.app.core.logging import get_logger
from apps.worker.agent.providers import LLMResponse, build_provider
from apps.worker.agent.state import IncidentAgentState

logger = get_logger(__name__)


def generate_hypotheses_node(state: IncidentAgentState) -> dict[str, Any]:
    """Sync entry point called by LangGraph — bridges to the async implementation.

    When called from a sync context (unit tests, non-async code), uses asyncio.run().
    When already inside a running event loop (LangGraph ainvoke), uses loop.run_until_complete
    via a new thread to avoid 'cannot run nested event loop'.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We're inside an async context (e.g., LangGraph ainvoke in async tests)
        # Run in a new thread with its own event loop to avoid nesting
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _generate_hypotheses_async(state))
            return future.result()
    else:
        return asyncio.run(_generate_hypotheses_async(state))


async def _generate_hypotheses_async(state: IncidentAgentState) -> dict[str, Any]:
    """Call the configured LLM provider to produce a grounded hypothesis."""
    evidence_records = state.get("evidence_records", [])
    signals = state.get("signals", {})
    min_confidence = state.get("min_confidence", 0.5)
    retrieved_runbooks = state.get("retrieved_runbooks", [])

    settings = get_settings()
    provider = build_provider(settings)

    logger.info(
        "llm_hypothesis_start",
        provider=provider.name,
        model=settings.llm_model,
        evidence_count=len(evidence_records),
    )

    try:
        llm_response: LLMResponse = await provider.generate_hypothesis(
            incident_id=state.get("incident_id", ""),
            service_name=state.get("service_name", ""),
            alert_type=state.get("alert_type", ""),
            severity=state.get("severity", ""),
            evidence_records=evidence_records,
            retrieved_runbooks=retrieved_runbooks,
            signals=signals,
            min_confidence=min_confidence,
            prompt_version=settings.prompt_version,
        )
    except Exception as exc:
        logger.error("llm_provider_error", provider=provider.name, error=str(exc))
        return {
            "status": "insufficient_evidence",
            "summary": f"LLM provider error ({provider.name}): {exc}",
            "selected_hypothesis": None,
            "hypotheses": [],
            "error_message": str(exc),
        }

    logger.info(
        "llm_hypothesis_done",
        provider=provider.name,
        is_mock=llm_response.is_mock,
        confidence=llm_response.confidence,
        root_cause=llm_response.root_cause,
        input_tokens=llm_response.input_tokens,
        output_tokens=llm_response.output_tokens,
    )

    # Insufficient evidence — LLM itself concluded it cannot form a hypothesis
    if llm_response.root_cause is None or llm_response.hypothesis_summary is None:
        return {
            "status": "insufficient_evidence",
            "summary": llm_response.reasoning
            or "Insufficient evidence to determine a reliable root cause.",
            "selected_hypothesis": None,
            "hypotheses": [],
            "input_tokens": llm_response.input_tokens,
            "output_tokens": llm_response.output_tokens,
        }

    # Confidence threshold check (also re-enforced by backend in validate_grounding)
    if llm_response.confidence < min_confidence:
        return {
            "status": "insufficient_evidence",
            "summary": (
                f"LLM confidence {llm_response.confidence:.0%} is below the required "
                f"threshold {min_confidence:.0%}."
            ),
            "selected_hypothesis": None,
            "hypotheses": [],
            "input_tokens": llm_response.input_tokens,
            "output_tokens": llm_response.output_tokens,
        }

    # Build the hypothesis dict — backend validate_grounding will check every cited ID
    hypothesis: dict[str, Any] = {
        "root_cause": llm_response.root_cause,
        "summary": llm_response.hypothesis_summary,
        "confidence": llm_response.confidence,
        "evidence_ids": llm_response.cited_evidence_ids,
        "reasoning": llm_response.reasoning,
        "provider": provider.name,
        "is_mock": llm_response.is_mock,
    }

    # Build recommendation hint — safety_check will allowlist-verify action_type
    recommendation_hint: dict[str, Any] | None = None
    if llm_response.action_type:
        recommendation_hint = {
            "action_type": llm_response.action_type,
            "parameters": llm_response.action_parameters,
            "rationale": llm_response.action_rationale or "",
        }

    return {
        "hypotheses": [hypothesis],
        "selected_hypothesis": hypothesis,
        "summary": llm_response.hypothesis_summary,
        "status": "running",
        "llm_recommendation_hint": recommendation_hint,
        "input_tokens": state.get("input_tokens", 0) + llm_response.input_tokens,
        "output_tokens": state.get("output_tokens", 0) + llm_response.output_tokens,
    }
