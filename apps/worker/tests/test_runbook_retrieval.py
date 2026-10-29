"""Tests for runbook parsing, indexing, retrieval, and LangGraph node."""

import uuid
from pathlib import Path

from apps.api.app.models.enums import EvidenceSourceType
from apps.worker.agent.nodes.retrieve_runbooks import retrieve_runbooks_node
from apps.worker.agent.runbooks import RunbookRetriever, parse_runbook_file
from apps.worker.agent.state import IncidentAgentState


def test_parse_runbook_file_success() -> None:
    path = Path(__file__).resolve().parents[3] / "runbooks" / "checkout-api-database-connection-exhaustion.md"
    assert path.exists()
    doc = parse_runbook_file(path)

    assert doc.file_name == "checkout-api-database-connection-exhaustion.md"
    assert doc.service == "checkout-api"
    assert doc.incident_type == "database_connection_exhaustion"
    assert doc.owner_team == "payments-team"
    assert "database connection exhaustion" in doc.title.lower()
    assert len(doc.symptoms) >= 1
    assert len(doc.likely_causes) >= 1
    assert len(doc.recommended_actions) >= 1
    assert "symptoms" in doc.sections
    assert "likely causes" in doc.sections
    assert "recommended actions" in doc.sections


def test_parse_runbook_file_malformed_frontmatter(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad-runbook.md"
    bad_file.write_text(
        "---\ninvalid_yaml: [unterminated\n---\n# Fallback Title\n\n## Symptoms\n- service down\n",
        encoding="utf-8",
    )
    doc = parse_runbook_file(bad_file)
    assert doc.file_name == "bad-runbook.md"
    assert doc.title == "Fallback Title"
    assert doc.service == ""
    assert "service down" in doc.symptoms


def test_runbook_retriever_load_and_retrieve() -> None:
    retriever = RunbookRetriever()
    assert len(retriever.documents) >= 2

    # Query for connection pool exhaustion symptoms
    matches = retriever.retrieve(
        service_name="checkout-api",
        query="database connection pool timeout error",
        top_k=2,
    )
    assert len(matches) > 0
    top_doc, score = matches[0]
    assert score > 0
    assert "connection" in top_doc.file_name or "checkout-api" in top_doc.service


def test_runbook_retriever_unrelated_query() -> None:
    retriever = RunbookRetriever()
    matches = retriever.retrieve(
        service_name="payment-processor",
        query="quantum computing entanglement failure",
        top_k=2,
    )
    # Should yield zero results or extremely low score
    assert len(matches) == 0 or matches[0][1] == 0.0


def test_runbook_retriever_as_connector_result() -> None:
    retriever = RunbookRetriever()
    results = retriever.retrieve_as_connector_result(
        service_name="checkout-api",
        query="checkout latency slow requests",
    )
    assert len(results) >= 1
    item = results[0]
    assert item.source_type == EvidenceSourceType.RUNBOOK
    assert "checkout" in item.source_name
    assert "Recommended action:" in item.summary
    assert item.query_params["service_name"] == "checkout-api"


def test_retrieve_runbooks_node_adds_evidence() -> None:
    state: IncidentAgentState = {
        "service_name": "checkout-api",
        "alert_type": "high_error_rate",
        "evidence_records": [{"summary": "db connection timeout detected in logs"}],
        "runbook_evidence": [],
    }

    result = retrieve_runbooks_node(state)
    assert "retrieved_runbooks" in result
    assert len(result["retrieved_runbooks"]) > 0
    assert len(result["runbook_evidence"]) > 0
    assert len(result["evidence_records"]) > 1

    first_runbook_ev = result["runbook_evidence"][0]
    assert first_runbook_ev["source_type"] == EvidenceSourceType.RUNBOOK
    assert "checkout-api" in first_runbook_ev["source_name"]


def test_retrieve_runbooks_node_deduplicates_existing() -> None:
    # If runbook already exists in evidence, don't duplicate it
    existing_id = str(uuid.uuid4())
    state: IncidentAgentState = {
        "service_name": "checkout-api",
        "alert_type": "high_error_rate",
        "evidence_records": [
            {
                "id": existing_id,
                "source_type": EvidenceSourceType.RUNBOOK,
                "source_name": "runbooks/checkout-api-database-connection-exhaustion.md",
                "summary": "Existing runbook evidence",
            }
        ],
        "runbook_evidence": [],
    }

    result = retrieve_runbooks_node(state)
    # Should not re-add the same runbook file as evidence record
    added_ids = [e.get("id") for e in result["evidence_records"] if e.get("id") == existing_id]
    assert len(added_ids) == 1
