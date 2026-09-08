import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.app.models import (
    AgentRun,
    Evidence,
    EvidenceSourceType,
    Hypothesis,
    HypothesisEvidence,
    IncidentEvent,
    Recommendation,
    RiskLevel,
    ToolCall,
)
from apps.api.app.schemas.investigation import (
    AgentRunCreate,
    EvidenceCreate,
    HypothesisCreate,
    RecommendationCreate,
    ToolCallCreate,
)
from apps.api.app.services import investigation_service as investigations

BASE = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
RAW_DATA: dict[str, Any] = {
    "results": [{"value": "0.35", "labels": {"service_name": "checkout-api"}}],
    "log": "  database connection timeout\n",
    "empty": None,
    "unicode": "Bằng chứng kiểm thử — not live data",
}


async def new_incident(client: AsyncClient, name: str = "checkout-api") -> uuid.UUID:
    response = await client.post(
        "/api/v1/alerts",
        json={
            "service_name": name,
            "alert_type": "high_error_rate",
            "severity": "critical",
            "started_at": BASE.isoformat(),
        },
    )
    assert response.status_code == 201
    return uuid.UUID(response.json()["incident_id"])


async def new_run(session: AsyncSession, incident_id: uuid.UUID) -> AgentRun:
    return await investigations.create_agent_run(
        session, incident_id, AgentRunCreate(prompt_version="test-fixture-v1")
    )


def evidence_payload(**overrides: Any) -> EvidenceCreate:
    return EvidenceCreate.model_validate(
        {
            "source_type": "metric",
            "source_name": "prometheus",
            "query": "  sum(rate(http_requests_total[1m]))\n",
            "query_params": {"service_name": "checkout-api", "step": 5},
            "summary": "Synthetic fixture for persistence tests, not a live measurement.",
            "raw_data": RAW_DATA,
            "time_range_start": BASE,
            "time_range_end": BASE + timedelta(minutes=1),
            "collected_at": BASE + timedelta(minutes=2),
            **overrides,
        }
    )


def tool_payload(**overrides: Any) -> ToolCallCreate:
    return ToolCallCreate.model_validate(
        {
            "tool_name": "query_metrics",
            "status": "succeeded",
            "input_payload": {"query": "up"},
            "output_payload": RAW_DATA,
            "started_at": BASE,
            "finished_at": BASE + timedelta(seconds=1),
            **overrides,
        }
    )


@pytest.mark.parametrize("source_type", list(EvidenceSourceType))
async def test_evidence_round_trip_with_source_query_and_raw_data(
    client: AsyncClient, session: AsyncSession, source_type: EvidenceSourceType
) -> None:
    incident_id = await new_incident(client)
    run = await new_run(session, incident_id)
    call = await investigations.record_tool_call(session, run.id, tool_payload())
    evidence = await investigations.record_evidence(
        session, run.id, evidence_payload(source_type=source_type, tool_call_id=call.id)
    )
    await session.commit()

    response = await client.get(f"/api/v1/incidents/{incident_id}/evidence/{evidence.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(evidence.id)
    assert data["agent_run_id"] == str(run.id)
    assert data["tool_call_id"] == str(call.id)
    assert data["source_type"] == source_type
    assert data["source_name"] == "prometheus"
    assert data["query"] == evidence.query
    assert data["query_params"] == {"service_name": "checkout-api", "step": 5}
    assert data["raw_data"] == RAW_DATA
    assert data["collected_at"] and data["time_range_start"] and data["time_range_end"]

    timeline = (await client.get(f"/api/v1/incidents/{incident_id}/timeline")).json()["events"]
    events = {event["event_type"]: event for event in timeline}
    assert events["evidence_collected"]["event_metadata"]["evidence_id"] == str(evidence.id)
    assert "agent_run_created" in events


async def test_pagination_filters_and_incident_isolation(
    client: AsyncClient, session: AsyncSession
) -> None:
    incident_id = await new_incident(client)
    other_id = await new_incident(client, "other-service")
    run = await new_run(session, incident_id)
    second_run = await new_run(session, incident_id)
    other_run = await new_run(session, other_id)
    records = []
    for index, source_type in enumerate(("metric", "log", "deployment")):
        records.append(
            await investigations.record_evidence(
                session,
                run.id,
                evidence_payload(
                    source_type=source_type, collected_at=BASE + timedelta(seconds=index)
                ),
            )
        )
    await investigations.record_evidence(session, second_run.id, evidence_payload())
    other = await investigations.record_evidence(session, other_run.id, evidence_payload())
    await session.commit()

    url = f"/api/v1/incidents/{incident_id}/evidence"
    data = (await client.get(url, params={"limit": 1, "offset": 1})).json()
    assert data["total"] == 4
    assert [item["id"] for item in data["items"]] == [str(records[1].id)]
    filtered = (await client.get(url, params={"source_type": "log"})).json()
    assert filtered["total"] == 1 and filtered["items"][0]["source_type"] == "log"
    assert (await client.get(url, params={"source_name": "missing"})).json()["total"] == 0
    assert (await client.get(url, params={"agent_run_id": str(run.id)})).json()["total"] == 3
    assert (await client.get(url, params={"agent_run_id": str(other_run.id)})).json()["total"] == 0
    assert (await client.get(f"{url}/{other.id}")).status_code == 404
    run_evidence = (await client.get(f"/api/v1/agent-runs/{run.id}/evidence")).json()
    assert run_evidence["total"] == 3
    assert all(item["agent_run_id"] == str(run.id) for item in run_evidence["items"])


async def test_run_and_tool_audit_endpoints(client: AsyncClient, session: AsyncSession) -> None:
    incident_id = await new_incident(client)
    run = await new_run(session, incident_id)
    await investigations.record_tool_call(session, run.id, tool_payload())
    await investigations.record_tool_call(
        session,
        run.id,
        tool_payload(
            tool_name="search_logs",
            status="failed",
            error_message="Loki timeout",
            output_payload={},
            started_at=BASE + timedelta(seconds=1),
        ),
    )
    await session.commit()
    runs = (await client.get(f"/api/v1/incidents/{incident_id}/agent-runs")).json()
    assert runs["total"] == 1 and runs["items"][0]["id"] == str(run.id)
    data = (await client.get(f"/api/v1/agent-runs/{run.id}")).json()
    assert data["prompt_version"] == "test-fixture-v1"
    assert data["input_tokens"] == data["output_tokens"] == 0
    assert data["model_name"] is None
    assert data["status"] == "pending"  # Creating a record is NOT executing an agent.
    calls = (
        await client.get(
            f"/api/v1/agent-runs/{run.id}/tool-calls", params={"limit": 1, "offset": 1}
        )
    ).json()
    assert calls["total"] == 2
    assert calls["items"][0]["error_message"] == "Loki timeout"
    all_calls = (await client.get(f"/api/v1/agent-runs/{run.id}/tool-calls")).json()
    assert all_calls["items"][0]["output_payload"] == RAW_DATA


async def test_empty_missing_and_invalid_requests(
    client: AsyncClient, session: AsyncSession
) -> None:
    incident_id = await new_incident(client)
    run = await new_run(session, incident_id)
    await session.commit()
    url = f"/api/v1/incidents/{incident_id}/evidence"
    assert (await client.get(url)).json() == {"items": [], "total": 0}
    assert (await client.get(f"/api/v1/agent-runs/{run.id}/tool-calls")).json() == {
        "items": [],
        "total": 0,
    }
    for path in (
        f"/api/v1/incidents/{uuid.uuid4()}/evidence",
        f"/api/v1/incidents/{uuid.uuid4()}/agent-runs",
        f"{url}/{uuid.uuid4()}",
        f"/api/v1/agent-runs/{uuid.uuid4()}",
        f"/api/v1/agent-runs/{uuid.uuid4()}/tool-calls",
        f"/api/v1/agent-runs/{uuid.uuid4()}/evidence",
    ):
        assert (await client.get(path)).status_code == 404
    for params in (
        {"limit": 0},
        {"limit": 201},
        {"offset": -1},
        {"source_type": "bogus"},
        {"agent_run_id": "bad-id"},
    ):
        assert (await client.get(url, params=params)).status_code == 422
    assert (await client.post(url, json={})).status_code == 405


@pytest.mark.parametrize(
    "overrides",
    [
        {"query": "   "},
        {"source_name": ""},
        {"summary": ""},
        {"source_type": "unknown"},
        {"raw_data": None},
        {"time_range_start": None},
        {"time_range_end": BASE - timedelta(seconds=1)},
        {"collected_at": "2026-09-08T12:00:00"},
        {"raw_data": {"invalid": float("nan")}},
    ],
)
def test_evidence_schema_rejects_invalid_provenance(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        evidence_payload(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "failed"},
        {"error_message": "unexpected"},
        {"finished_at": BASE - timedelta(seconds=1)},
        {"tool_name": "  "},
    ],
)
def test_tool_call_schema_rejects_invalid_audit_records(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        tool_payload(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"confidence": float("nan")},
        {"evidence_ids": []},
    ],
)
def test_hypothesis_schema_requires_citations_and_valid_confidence(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        HypothesisCreate.model_validate(
            {
                "root_cause": "deployment_regression",
                "summary": "Test hypothesis",
                "confidence": 0.8,
                "evidence_ids": [uuid.uuid4()],
                **overrides,
            }
        )


async def test_grounded_hypothesis_and_proposal(client: AsyncClient, session: AsyncSession) -> None:
    incident_id = await new_incident(client)
    run = await new_run(session, incident_id)
    evidence = await investigations.record_evidence(session, run.id, evidence_payload())
    hypothesis = await investigations.record_hypothesis(
        session,
        run.id,
        HypothesisCreate(
            root_cause="deployment_regression",
            summary="Fixture conclusion",
            confidence=0.8,
            evidence_ids=[evidence.id, evidence.id],
        ),
    )
    recommendation = await investigations.record_recommendation(
        session,
        run.id,
        RecommendationCreate(
            hypothesis_id=hypothesis.id,
            action_type="simulated_rollback",
            parameters={"to_version": "v1.4.1"},
            rationale="Fixture proposal",
            risk_level=RiskLevel.MEDIUM,
        ),
    )
    await session.commit()
    assert recommendation.status == "proposed" and recommendation.requires_approval is True
    assert await session.scalar(select(func.count()).select_from(HypothesisEvidence)) == 1
    assert await session.scalar(select(func.count()).select_from(Recommendation)) == 1


async def test_cross_run_and_missing_references_rejected_before_writes(
    client: AsyncClient, session: AsyncSession
) -> None:
    incident_id = await new_incident(client)
    run = await new_run(session, incident_id)
    other_run = await new_run(session, incident_id)
    call = await investigations.record_tool_call(session, run.id, tool_payload())
    failed = await investigations.record_tool_call(
        session, run.id, tool_payload(status="failed", error_message="timeout", output_payload={})
    )
    evidence = await investigations.record_evidence(session, run.id, evidence_payload())
    for run_id, call_id in ((other_run.id, call.id), (run.id, failed.id), (run.id, uuid.uuid4())):
        with pytest.raises(investigations.InvalidEvidenceReferenceError):
            await investigations.record_evidence(
                session, run_id, evidence_payload(tool_call_id=call_id)
            )
    for citation in (evidence.id, uuid.uuid4()):
        with pytest.raises(investigations.InvalidEvidenceReferenceError):
            await investigations.record_hypothesis(
                session,
                other_run.id,
                HypothesisCreate(
                    root_cause="test", summary="test", confidence=0.5, evidence_ids=[citation]
                ),
            )
    assert await session.scalar(select(func.count()).select_from(Hypothesis)) == 0
    assert await session.scalar(select(func.count()).select_from(Evidence)) == 1


async def test_unknown_incident_or_run_does_not_create_records(session: AsyncSession) -> None:
    with pytest.raises(investigations.InvestigationNotFoundError):
        await new_run(session, uuid.uuid4())
    with pytest.raises(investigations.InvestigationNotFoundError):
        await investigations.record_evidence(session, uuid.uuid4(), evidence_payload())
    with pytest.raises(investigations.InvestigationNotFoundError):
        await investigations.record_tool_call(session, uuid.uuid4(), tool_payload())
    assert await session.scalar(select(func.count()).select_from(AgentRun)) == 0


async def test_recommendations_require_a_grounded_hypothesis_in_the_same_run(
    client: AsyncClient, session: AsyncSession
) -> None:
    incident_id = await new_incident(client)
    run = await new_run(session, incident_id)
    other_run = await new_run(session, incident_id)
    evidence = await investigations.record_evidence(session, other_run.id, evidence_payload())
    other_hypothesis = await investigations.record_hypothesis(
        session,
        other_run.id,
        HypothesisCreate(
            root_cause="fixture", summary="Fixture", confidence=0.5, evidence_ids=[evidence.id]
        ),
    )
    ungrounded = Hypothesis(
        agent_run_id=run.id, root_cause="fixture", summary="Uncited fixture", confidence=0.5
    )
    session.add(ungrounded)
    await session.flush()
    for hypothesis_id in (uuid.uuid4(), other_hypothesis.id, ungrounded.id):
        with pytest.raises(investigations.InvalidEvidenceReferenceError):
            await investigations.record_recommendation(
                session,
                run.id,
                RecommendationCreate(
                    hypothesis_id=hypothesis_id,
                    action_type="simulated_rollback",
                    rationale="Fixture proposal",
                    risk_level=RiskLevel.MEDIUM,
                ),
            )
    assert await session.scalar(select(func.count()).select_from(Recommendation)) == 0


@pytest.mark.parametrize("override", [{"requires_approval": False}, {"status": "executed"}])
def test_proposal_input_cannot_request_execution(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RecommendationCreate.model_validate(
            {
                "hypothesis_id": uuid.uuid4(),
                "action_type": "simulated_rollback",
                "rationale": "Fixture proposal",
                "risk_level": "medium",
                **override,
            }
        )


async def test_caller_can_rollback_entire_collection(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    incident_id = await new_incident(client)
    async with session_factory() as session:
        run = await new_run(session, incident_id)
        call = await investigations.record_tool_call(session, run.id, tool_payload())
        await investigations.record_evidence(
            session, run.id, evidence_payload(tool_call_id=call.id)
        )
        await session.rollback()
    async with session_factory() as session:
        for model in (AgentRun, ToolCall, Evidence):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
        assert await session.scalar(select(func.count()).select_from(IncidentEvent)) == 1


@pytest.mark.parametrize(
    "mismatch",
    ["incident", "tool", "citation", "confidence", "recommendation_run", "status", "approval"],
)
async def test_database_constraints_reject_bypassing_service_validation(
    client: AsyncClient, session: AsyncSession, mismatch: str
) -> None:
    incident_id = await new_incident(client)
    other_id = await new_incident(client, "other-service")
    run = await new_run(session, incident_id)
    other_run = await new_run(session, other_id)
    other_call = await investigations.record_tool_call(session, other_run.id, tool_payload())
    other_evidence = await investigations.record_evidence(session, other_run.id, evidence_payload())
    hypothesis = Hypothesis(agent_run_id=run.id, root_cause="test", summary="test", confidence=0.5)
    session.add(hypothesis)
    await session.flush()
    await session.commit()
    if mismatch in ("incident", "tool"):
        record = Evidence(
            incident_id=other_id if mismatch == "incident" else incident_id,
            agent_run_id=run.id,
            **evidence_payload(
                tool_call_id=other_call.id if mismatch == "tool" else None
            ).model_dump(),
        )
        session.add(record)
    elif mismatch == "citation":
        session.add(
            HypothesisEvidence(
                hypothesis_id=hypothesis.id, evidence_id=other_evidence.id, agent_run_id=run.id
            )
        )
    elif mismatch == "confidence":
        hypothesis.confidence = 1.5
    else:
        session.add(
            Recommendation(
                agent_run_id=other_run.id if mismatch == "recommendation_run" else run.id,
                hypothesis_id=hypothesis.id,
                action_type="simulated_rollback",
                parameters={},
                rationale="Fixture",
                risk_level=RiskLevel.MEDIUM,
                status="executed" if mismatch == "status" else "proposed",
                requires_approval=mismatch != "approval",
            )
        )
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()
