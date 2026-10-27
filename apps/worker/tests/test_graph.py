"""Tests for LangGraph compilation, execution, conditional routing, and anti-hallucination."""

import uuid
from typing import Any

import pytest
from langgraph.graph.state import CompiledStateGraph

from apps.worker.agent.graph import (
    build_investigation_graph,
    compiled_investigation_graph,
    should_continue_investigation,
)
from apps.worker.agent.state import IncidentAgentState


def test_build_and_compile_investigation_graph() -> None:
    builder = build_investigation_graph()
    assert builder is not None
    compiled = builder.compile()
    assert isinstance(compiled, CompiledStateGraph)
    # Check registered nodes
    assert "retrieve_runbooks" in compiled.nodes
    assert "correlate_evidence" in compiled.nodes
    assert "generate_hypotheses" in compiled.nodes
    assert "validate_grounding" in compiled.nodes
    assert "propose_actions" in compiled.nodes
    assert "safety_check" in compiled.nodes


def test_conditional_routing_branches() -> None:
    # 1. Healthy state routes to propose_actions
    healthy_state: IncidentAgentState = {
        "status": "running",
        "selected_hypothesis": {
            "root_cause": "deployment_regression",
            "evidence_ids": [str(uuid.uuid4())],
        },
    }
    assert should_continue_investigation(healthy_state) == "propose_actions"

    # 2. Insufficient evidence routes to end
    insufficient_state: IncidentAgentState = {
        "status": "insufficient_evidence",
        "selected_hypothesis": None,
    }
    assert should_continue_investigation(insufficient_state) == "end"

    # 3. Missing selected_hypothesis routes to end
    no_hyp_state: IncidentAgentState = {
        "status": "running",
        "selected_hypothesis": None,
    }
    assert should_continue_investigation(no_hyp_state) == "end"


def test_graph_execution_success_path() -> None:
    incident_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    ev_deploy = {
        "id": str(uuid.uuid4()),
        "source_type": "deployment",
        "summary": "v1.4.2 deployed by ci-bot",
        "raw_data": {"commit": "a1b2c3d"},
    }
    ev_metric = {
        "id": str(uuid.uuid4()),
        "source_type": "metric",
        "summary": "error rate increased to 35%",
        "raw_data": {"value": 0.35},
    }
    ev_log = {
        "id": str(uuid.uuid4()),
        "source_type": "log",
        "summary": "database connection timeout after 5000ms",
        "raw_data": {"streams": []},
    }

    initial_state: IncidentAgentState = {
        "incident_id": incident_id,
        "agent_run_id": run_id,
        "service_name": "checkout-api",
        "alert_type": "high_error_rate",
        "severity": "critical",
        "min_confidence": 0.6,
        "evidence_records": [ev_deploy, ev_metric, ev_log],
        "metrics_evidence": [ev_metric],
        "logs_evidence": [ev_log],
        "deployments_evidence": [ev_deploy],
        "runbook_evidence": [],
        "retrieved_runbooks": [],
    }

    final_state = compiled_investigation_graph.invoke(initial_state)

    assert final_state["status"] == "completed"
    assert final_state["safety_check_passed"] is True
    assert final_state["selected_hypothesis"] is not None
    assert final_state["selected_hypothesis"]["root_cause"] == "deployment_regression"
    assert final_state["selected_recommendation"] is not None
    assert final_state["selected_recommendation"]["action_type"] == "simulated_rollback"
    assert final_state["selected_recommendation"]["requires_approval"] is True
    # Runbook RAG ran and found relevant runbooks
    assert len(final_state.get("retrieved_runbooks", [])) > 0
    assert len(final_state.get("runbook_evidence", [])) > 0


def test_graph_execution_fake_evidence_id_terminates_at_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate a model/node that hallucinates an evidence ID not present in records."""
    fake_id = str(uuid.uuid4())
    real_deploy_id = str(uuid.uuid4())

    def fake_generate_hypotheses(state: IncidentAgentState) -> dict[str, Any]:
        return {
            "selected_hypothesis": {
                "root_cause": "fabricated_cause",
                "summary": "Hallucinated conclusion",
                "confidence": 0.99,
                "evidence_ids": [real_deploy_id, fake_id],  # fake_id is not in evidence_records!
            },
            "status": "running",
        }

    monkeypatch.setattr(
        "apps.worker.agent.graph.generate_hypotheses_node",
        fake_generate_hypotheses,
    )

    # Rebuild graph with mocked node
    test_graph = build_investigation_graph().compile()

    initial_state: IncidentAgentState = {
        "incident_id": str(uuid.uuid4()),
        "agent_run_id": str(uuid.uuid4()),
        "service_name": "checkout-api",
        "alert_type": "high_error_rate",
        "evidence_records": [{"id": real_deploy_id, "source_type": "deployment"}],
    }

    final_state = test_graph.invoke(initial_state)

    # Must be rejected by validate_grounding and routed to END!
    assert final_state["status"] == "insufficient_evidence"
    assert final_state["selected_hypothesis"] is None
    assert "Hallucinated evidence IDs cited" in (final_state.get("error_message") or "")
    # propose_actions and safety_check must NOT have run
    assert final_state.get("selected_recommendation") is None
    assert final_state.get("safety_check_passed") is not True


def test_graph_execution_insufficient_evidence_terminates_without_actions() -> None:
    # Missing deployment: only a single metric record provided
    ev_metric = {
        "id": str(uuid.uuid4()),
        "source_type": "metric",
        "summary": "single metric data point",
    }
    initial_state: IncidentAgentState = {
        "incident_id": str(uuid.uuid4()),
        "agent_run_id": str(uuid.uuid4()),
        "service_name": "checkout-api",
        "alert_type": "high_error_rate",
        "evidence_records": [ev_metric],
        "metrics_evidence": [ev_metric],
    }

    final_state = compiled_investigation_graph.invoke(initial_state)

    assert final_state["status"] == "insufficient_evidence"
    assert final_state.get("selected_hypothesis") is None
    assert final_state.get("selected_recommendation") is None
    assert "Insufficient evidence" in final_state["summary"]
