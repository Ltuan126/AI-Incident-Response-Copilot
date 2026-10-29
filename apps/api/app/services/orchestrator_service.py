"""Orchestrator tying evidence collection, LangGraph agent, and approvals."""

import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import Settings
from apps.api.app.models import (
    AgentRun,
    AgentRunStatus,
    Alert,
    Evidence,
    EvidenceSourceType,
    Incident,
    IncidentAlert,
    IncidentStatus,
    RiskLevel,
    Service,
)
from apps.api.app.schemas.analysis import AnalysisHypothesisRead, AnalysisRecommendationRead
from apps.api.app.schemas.collection import CollectEvidenceRequest
from apps.api.app.schemas.investigation import (
    ApprovalRead,
    HypothesisCreate,
    RecommendationCreate,
)
from apps.api.app.schemas.orchestrator import (
    InvestigateIncidentRequest,
    InvestigateIncidentResponse,
)
from apps.api.app.services.approval_service import request_approval
from apps.api.app.services.collection_service import (
    CollectionNotFoundError,
    collect_incident_evidence,
)
from apps.api.app.services.investigation_service import (
    record_hypothesis,
    record_recommendation,
)
from apps.worker.agent.graph import compiled_investigation_graph
from apps.worker.agent.state import IncidentAgentState


class OrchestrationError(ValueError):
    """An incident investigation could not be completed."""


async def investigate_incident(
    session: AsyncSession,
    incident_id: uuid.UUID,
    request: InvestigateIncidentRequest,
    settings: Settings,
) -> InvestigateIncidentResponse:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise CollectionNotFoundError("Incident not found")

    service = await session.get(Service, incident.service_id)
    service_name = service.name if service else "unknown"

    alert_type = (
        await session.scalar(
            select(Alert.alert_type)
            .join(IncidentAlert, IncidentAlert.alert_id == Alert.id)
            .where(IncidentAlert.incident_id == incident_id)
            .limit(1)
        )
        or incident.title
    )

    # Step 1: Collect Telemetry Evidence
    collection_request = CollectEvidenceRequest(
        lookback_seconds=request.lookback_seconds,
        step_seconds=request.step_seconds,
        log_limit=request.log_limit,
    )
    collection_result = await collect_incident_evidence(
        session, incident_id, collection_request, settings
    )
    agent_run_id = collection_result.agent_run_id

    run = await session.get(AgentRun, agent_run_id)
    if run is None:
        raise CollectionNotFoundError("Agent run not found")

    run.status = AgentRunStatus.RUNNING
    run.started_at = run.started_at or datetime.now(UTC)
    run.provider = "langgraph"
    run.model_name = "incident-agent-graph-v1"
    run.prompt_version = settings.prompt_version
    if incident.status in (IncidentStatus.NEW, IncidentStatus.COLLECTING_EVIDENCE):
        incident.status = IncidentStatus.ANALYZING
    await session.flush()

    # Step 2: Load Collected Evidence Rows
    evidence_rows = list(
        await session.scalars(
            select(Evidence)
            .where(Evidence.agent_run_id == agent_run_id)
            .order_by(Evidence.collected_at.asc(), Evidence.id.asc())
        )
    )
    evidence_records = [
        {
            "id": str(e.id),
            "source_type": e.source_type.value
            if hasattr(e.source_type, "value")
            else str(e.source_type),
            "source_name": e.source_name,
            "query": e.query,
            "query_params": e.query_params,
            "summary": e.summary,
            "raw_data": e.raw_data,
            "collected_at": e.collected_at.isoformat() if e.collected_at else None,
        }
        for e in evidence_rows
    ]

    initial_state: IncidentAgentState = {
        "incident_id": str(incident_id),
        "agent_run_id": str(agent_run_id),
        "service_name": service_name,
        "alert_type": alert_type,
        "severity": str(incident.severity),
        "started_at": incident.started_at.isoformat() if incident.started_at else None,
        "lookback_seconds": request.lookback_seconds,
        "step_seconds": request.step_seconds,
        "log_limit": request.log_limit,
        "min_confidence": request.min_confidence,
        "metrics_evidence": [e for e in evidence_records if e["source_type"] == "metric"],
        "logs_evidence": [e for e in evidence_records if e["source_type"] == "log"],
        "deployments_evidence": [e for e in evidence_records if e["source_type"] == "deployment"],
        "runbook_evidence": [e for e in evidence_records if e["source_type"] == "runbook"],
        "evidence_records": evidence_records,
        "retrieved_runbooks": [],
        "signals": {},
        "hypotheses": [],
        "selected_hypothesis": None,
        "llm_recommendation_hint": None,
        "recommendations": [],
        "selected_recommendation": None,
        "status": "running",
        "summary": "",
        "error_message": None,
        "safety_check_passed": False,
        "requires_approval": True,
        "tool_calls": [],
        "input_tokens": 0,
        "output_tokens": 0,
    }

    # Step 3: Execute Controlled LangGraph Investigation Workflow
    raw_state = await compiled_investigation_graph.ainvoke(initial_state)
    final_state = cast(IncidentAgentState, raw_state)

    # Persist any newly retrieved runbook evidence items into DB
    for r_ev in final_state.get("runbook_evidence", []):
        r_id = uuid.UUID(str(r_ev["id"]))
        existing = await session.get(Evidence, r_id)
        if existing is None:
            new_ev = Evidence(
                id=r_id,
                incident_id=incident_id,
                agent_run_id=agent_run_id,
                source_type=EvidenceSourceType.RUNBOOK,
                source_name=r_ev.get("source_name", "runbooks"),
                query=r_ev.get("query", ""),
                query_params=r_ev.get("query_params", {}),
                summary=r_ev.get("summary", ""),
                raw_data=r_ev.get("raw_data", {}),
                collected_at=datetime.now(UTC),
            )
            session.add(new_ev)
            await session.flush()

    selected_hyp = final_state.get("selected_hypothesis")
    selected_rec = final_state.get("selected_recommendation")
    is_insufficient = final_state.get("status") == "insufficient_evidence" or selected_hyp is None

    if is_insufficient:
        run.status = AgentRunStatus.INSUFFICIENT_EVIDENCE
        run.finished_at = datetime.now(UTC)
        run.error_message = (
            final_state.get("error_message")
            or "Insufficient evidence to determine a reliable root cause."
        )
        await session.flush()
        await session.refresh(incident)

        total_ev_count = await session.scalar(
            select(func.count()).select_from(Evidence).where(Evidence.agent_run_id == agent_run_id)
        ) or len(evidence_rows)
        return InvestigateIncidentResponse(
            incident_id=incident_id,
            agent_run_id=agent_run_id,
            incident_status=incident.status,
            evidence_count=total_ev_count,
            hypothesis=None,
            recommendation=None,
            approval=None,
            investigated_at=run.finished_at,
        )

    # Step 4: Record Grounded Hypothesis
    if selected_hyp is None:
        raise OrchestrationError("Expected selected hypothesis from agent")
    cited_uuids = [uuid.UUID(str(cid)) for cid in selected_hyp["evidence_ids"]]
    hypothesis = await record_hypothesis(
        session,
        agent_run_id,
        HypothesisCreate(
            root_cause=selected_hyp["root_cause"],
            summary=selected_hyp["summary"],
            confidence=selected_hyp["confidence"],
            evidence_ids=cited_uuids,
        ),
    )

    # Step 5: Record Recommended Remediation
    recommendation = None
    if selected_rec is not None:
        risk_level_val = selected_rec.get("risk_level", RiskLevel.MEDIUM)
        if isinstance(risk_level_val, str):
            risk_level_val = RiskLevel(risk_level_val)
        recommendation = await record_recommendation(
            session,
            agent_run_id,
            RecommendationCreate(
                hypothesis_id=hypothesis.id,
                action_type=selected_rec["action_type"],
                parameters=selected_rec.get("parameters", {}),
                rationale=selected_rec.get("rationale", ""),
                risk_level=risk_level_val,
            ),
        )

    run.status = AgentRunStatus.COMPLETED
    run.finished_at = datetime.now(UTC)
    run.error_message = None
    await session.flush()

    # Step 6: Automatically Request Approval if required
    approval_read: ApprovalRead | None = None
    if (
        recommendation is not None
        and request.auto_request_approval
        and selected_rec
        and selected_rec.get("requires_approval", True)
    ):
        approval = await request_approval(session, recommendation.id)
        approval_read = ApprovalRead.model_validate(approval)

    await session.refresh(incident)
    total_ev_count = await session.scalar(
        select(func.count()).select_from(Evidence).where(Evidence.agent_run_id == agent_run_id)
    ) or len(evidence_rows)

    return InvestigateIncidentResponse(
        incident_id=incident_id,
        agent_run_id=agent_run_id,
        incident_status=incident.status,
        evidence_count=total_ev_count,
        hypothesis=AnalysisHypothesisRead(
            id=hypothesis.id,
            root_cause=hypothesis.root_cause,
            summary=hypothesis.summary,
            confidence=hypothesis.confidence,
            evidence_ids=cited_uuids,
        ),
        recommendation=AnalysisRecommendationRead(
            id=recommendation.id,
            action_type=recommendation.action_type,
            parameters=recommendation.parameters,
            rationale=recommendation.rationale,
            risk_level=recommendation.risk_level,
            requires_approval=recommendation.requires_approval,
            status=recommendation.status,
        )
        if recommendation
        else None,
        approval=approval_read,
        investigated_at=run.finished_at,
    )
