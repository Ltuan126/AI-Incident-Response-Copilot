"""LangGraph node: retrieve relevant runbooks via RAG."""

import uuid
from datetime import UTC, datetime
from typing import Any

from apps.api.app.models.enums import EvidenceSourceType
from apps.worker.agent.runbooks import RunbookRetriever
from apps.worker.agent.state import IncidentAgentState


def retrieve_runbooks_node(state: IncidentAgentState) -> dict[str, Any]:
    """Search and retrieve runbooks relevant to the service and incident symptoms."""
    service_name = state.get("service_name", "")
    alert_type = state.get("alert_type", "")

    # Formulate query text from alert and existing evidence summaries
    summaries: list[str] = [alert_type]
    for ev in state.get("evidence_records", []):
        summaries.append(ev.get("summary", ""))
    query_text = " ".join(summaries)

    retriever = RunbookRetriever()
    matches = retriever.retrieve(service_name=service_name, query=query_text, top_k=2)

    retrieved_info: list[dict[str, Any]] = []
    runbook_evidence: list[dict[str, Any]] = list(state.get("runbook_evidence", []))
    all_evidence = list(state.get("evidence_records", []))

    for doc, score in matches:
        doc_dict = {
            "file_name": doc.file_name,
            "title": doc.title,
            "service": doc.service,
            "incident_type": doc.incident_type,
            "owner_team": doc.owner_team,
            "symptoms": doc.symptoms,
            "likely_causes": doc.likely_causes,
            "recommended_actions": doc.recommended_actions,
            "relevance_score": score,
        }
        retrieved_info.append(doc_dict)

        # Check if runbook is already stored in evidence
        exists = any(
            ev.get("source_type") == EvidenceSourceType.RUNBOOK
            and ev.get("source_name") == f"runbooks/{doc.file_name}"
            for ev in all_evidence
        )
        if not exists:
            ev_id = str(uuid.uuid4())
            action_text = (
                "; ".join(doc.recommended_actions[:2])
                if doc.recommended_actions
                else "Follow standard procedures"
            )
            summary_text = (
                f"Runbook '{doc.title}' ({doc.file_name}): Recommended action: {action_text}"
            )
            ev_record = {
                "id": ev_id,
                "source_type": EvidenceSourceType.RUNBOOK,
                "source_name": f"runbooks/{doc.file_name}",
                "query": f"service={service_name} query={query_text[:60]}",
                "summary": summary_text,
                "raw_data": doc_dict,
                "collected_at": datetime.now(UTC).isoformat(),
            }
            runbook_evidence.append(ev_record)
            all_evidence.append(ev_record)

    return {
        "retrieved_runbooks": retrieved_info,
        "runbook_evidence": runbook_evidence,
        "evidence_records": all_evidence,
    }
