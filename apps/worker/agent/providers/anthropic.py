"""AnthropicProvider — Claude-backed LLM provider.

Switch via environment variable:
    LLM_PROVIDER=anthropic
    ANTHROPIC_API_KEY=sk-ant-...
    LLM_MODEL=claude-sonnet-4-5   # or claude-opus-4, etc.

Architecture invariant:
    LLM produces: Evidence → Hypothesis → Reasoning → Recommendation
    Backend then validates:
        1. cited_evidence_ids exist in collected records (anti-hallucination)
        2. confidence >= min_confidence threshold
        3. action_type is in ALLOWED_ACTIONS allowlist
        4. human approval still required before execution

Requires:  pip install anthropic
"""

from __future__ import annotations

import json
import logging
from typing import Any

from apps.worker.agent.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

_ALLOWED_ACTIONS = frozenset(
    {"simulated_restart", "simulated_rollback", "simulated_scale", "create_incident_note"}
)

_SYSTEM_PROMPT = """\
You are an evidence-grounded Incident Response Copilot. Your role is to reason over \
verified telemetry, logs, and deployment events to identify root causes.

## Rules
1. NEVER fabricate technical conclusions without data. If evidence is ambiguous or absent, \
set root_cause and hypothesis_summary to null and confidence to 0.0.
2. Every hypothesis MUST cite only evidence IDs from the provided list — never invent IDs.
3. Proposed action_type MUST be one of: simulated_restart, simulated_rollback, \
simulated_scale, create_incident_note. If none is appropriate, set it to null.
4. Mutating actions ALWAYS require human approval — do not suggest bypassing this.

## Output Format
Respond with a single JSON object matching this schema exactly:
{
  "reasoning": "<step-by-step chain: evidence → signals → hypothesis → recommendation>",
  "root_cause": "<string or null>",
  "hypothesis_summary": "<string or null>",
  "confidence": <float 0.0-1.0>,
  "cited_evidence_ids": ["<uuid>", ...],
  "action_type": "<string or null>",
  "action_parameters": {},
  "action_rationale": "<string or null>"
}
"""


def _build_user_message(
    incident_id: str,
    service_name: str,
    alert_type: str,
    severity: str,
    evidence_records: list[dict[str, Any]],
    retrieved_runbooks: list[dict[str, Any]],
    signals: dict[str, Any],
    min_confidence: float,
) -> str:
    evidence_text = json.dumps(
        [
            {
                "id": e.get("id"),
                "source_type": e.get("source_type"),
                "summary": e.get("summary", ""),
                "raw_data": e.get("raw_data", {}),
            }
            for e in evidence_records
        ],
        indent=2,
    )
    runbooks_text = json.dumps(
        [
            {
                "title": rb.get("title"),
                "symptoms": rb.get("symptoms", []),
                "likely_causes": rb.get("likely_causes", []),
                "recommended_actions": rb.get("recommended_actions", []),
            }
            for rb in retrieved_runbooks
        ],
        indent=2,
    )
    return f"""\
## Incident Context
- incident_id: {incident_id}
- service: {service_name}
- alert_type: {alert_type}
- severity: {severity}
- min_confidence_required: {min_confidence}

## Collected Evidence
{evidence_text}

## Correlated Signals
{json.dumps(signals, indent=2)}

## Retrieved Runbooks
{runbooks_text}

Analyse the evidence above and respond with the JSON object described in the system prompt.
"""


class AnthropicProvider(LLMProvider):
    """Sends structured prompts to Claude and parses JSON hypothesis output."""

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        try:
            import anthropic  # type: ignore[import-untyped]

            self._client: Any = anthropic.AsyncAnthropic(api_key=api_key)
        except ImportError as exc:
            raise ImportError(
                "Install the Anthropic SDK:  pip install anthropic"
            ) from exc
        self._model = model
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "anthropic"

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
        import anthropic  # type: ignore[import-untyped]

        user_message = _build_user_message(
            incident_id=incident_id,
            service_name=service_name,
            alert_type=alert_type,
            severity=severity,
            evidence_records=evidence_records,
            retrieved_runbooks=retrieved_runbooks,
            signals=signals,
            min_confidence=min_confidence,
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                timeout=self._timeout,
            )
        except anthropic.APIError as exc:
            logger.error("anthropic_api_error", error=str(exc))
            raise

        raw_text: str = response.content[0].text
        input_tokens: int = response.usage.input_tokens
        output_tokens: int = response.usage.output_tokens

        # Strip markdown fences if Claude wrapped the JSON
        stripped = raw_text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()

        try:
            parsed: dict[str, Any] = json.loads(stripped)
        except json.JSONDecodeError:
            logger.warning("anthropic_json_parse_failed", raw=raw_text[:500])
            # Return empty response; backend grounding check will reject it
            return LLMResponse(
                reasoning=raw_text,
                root_cause=None,
                hypothesis_summary=None,
                confidence=0.0,
                cited_evidence_ids=[],
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                is_mock=False,
            )

        return LLMResponse(
            reasoning=parsed.get("reasoning", ""),
            root_cause=parsed.get("root_cause"),
            hypothesis_summary=parsed.get("hypothesis_summary"),
            confidence=float(parsed.get("confidence", 0.0)),
            cited_evidence_ids=parsed.get("cited_evidence_ids", []),
            action_type=parsed.get("action_type"),
            action_parameters=parsed.get("action_parameters", {}),
            action_rationale=parsed.get("action_rationale"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            is_mock=False,
        )
