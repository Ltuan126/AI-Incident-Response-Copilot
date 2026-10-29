"""OpenAIProvider — GPT-backed LLM provider.

Switch via environment variable:
    LLM_PROVIDER=openai
    OPENAI_API_KEY=sk-...
    LLM_MODEL=gpt-4o   # or gpt-4o-mini, o1-mini, etc.

Architecture invariant: identical to AnthropicProvider —
    LLM only proposes; backend deterministic checks enforce correctness.

Requires:  pip install openai
"""

from __future__ import annotations

import json
import logging
from typing import Any

from apps.worker.agent.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are an evidence-grounded Incident Response Copilot. Reason over the provided \
telemetry, logs, and deployment events to identify root causes.

## Rules
1. NEVER fabricate conclusions without data. If evidence is ambiguous or absent, \
set root_cause and hypothesis_summary to null and confidence to 0.0.
2. Every hypothesis MUST cite only evidence IDs present in the provided list.
3. action_type MUST be one of: simulated_restart, simulated_rollback, \
simulated_scale, create_incident_note — or null.
4. All mutating actions require human approval. Do not suggest bypassing it.

## Output Format
Respond ONLY with a single valid JSON object:
{
  "reasoning": "<chain: evidence → signals → hypothesis → recommendation>",
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

Analyse the evidence and respond with the JSON object described in the system prompt.
"""


class OpenAIProvider(LLMProvider):
    """Sends structured prompts to GPT models and parses JSON hypothesis output."""

    def __init__(self, api_key: str, model: str, timeout: float, base_url: str = "") -> None:
        try:
            import openai  # type: ignore[import-untyped]

            kwargs: dict[str, Any] = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client: Any = openai.AsyncOpenAI(**kwargs)
        except ImportError as exc:
            raise ImportError(
                "Install the OpenAI SDK:  pip install openai"
            ) from exc
        self._model = model
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "openai"

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
        import openai  # type: ignore[import-untyped]

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
            response = await self._client.chat.completions.create(
                model=self._model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                timeout=self._timeout,
            )
        except openai.APIError as exc:
            logger.error("openai_api_error", error=str(exc))
            raise

        raw_text: str = response.choices[0].message.content or ""
        input_tokens: int = response.usage.prompt_tokens if response.usage else 0
        output_tokens: int = response.usage.completion_tokens if response.usage else 0

        try:
            parsed: dict[str, Any] = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.warning("openai_json_parse_failed", raw=raw_text[:500])
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
