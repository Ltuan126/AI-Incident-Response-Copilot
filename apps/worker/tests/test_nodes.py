"""Unit tests for individual LangGraph investigation nodes."""

import uuid

from apps.api.app.models.enums import RiskLevel
from apps.worker.agent.nodes.correlate_evidence import correlate_evidence_node
from apps.worker.agent.nodes.generate_hypotheses import generate_hypotheses_node
from apps.worker.agent.nodes.propose_actions import propose_actions_node
from apps.worker.agent.nodes.safety_check import safety_check_node
from apps.worker.agent.nodes.validate_grounding import validate_grounding_node
from apps.worker.agent.state import IncidentAgentState


def test_correlate_evidence_node_signals_all_sources() -> None:
    ev1 = {"id": str(uuid.uuid4()), "source_type": "metric", "summary": "error rate rose to 35%"}
    ev2 = {"id": str(uuid.uuid4()), "source_type": "log", "summary": "database connection timeout"}
    ev3 = {"id": str(uuid.uuid4()), "source_type": "deployment", "summary": "deployed v1.4.2"}
    state: IncidentAgentState = {"evidence_records": [ev1, ev2, ev3]}

    result = correlate_evidence_node(state)
    signals = result["signals"]
    assert signals["has_deployment"] is True
    assert signals["has_error_logs"] is True
    assert signals["has_metric_anomaly"] is True
    assert signals["is_connection_exhaustion"] is True
    assert signals["metrics_count"] == 1
    assert signals["logs_count"] == 1
    assert signals["deployments_count"] == 1


def test_correlate_evidence_node_no_deployment() -> None:
    ev1 = {"id": str(uuid.uuid4()), "source_type": "metric", "summary": "error rate rose"}
    state: IncidentAgentState = {"evidence_records": [ev1]}

    result = correlate_evidence_node(state)
    signals = result["signals"]
    assert signals["has_deployment"] is False
    assert signals["deployments_count"] == 0


def test_generate_hypotheses_node_success() -> None:
    id_deploy = str(uuid.uuid4())
    id_metric = str(uuid.uuid4())
    id_log = str(uuid.uuid4())

    state: IncidentAgentState = {
        "evidence_records": [
            {"id": id_deploy, "source_type": "deployment"},
            {"id": id_metric, "source_type": "metric"},
            {"id": id_log, "source_type": "log"},
        ],
        "signals": {
            "has_deployment": True,
            "has_error_logs": True,
            "has_metric_anomaly": True,
            "is_connection_exhaustion": True,
        },
        "min_confidence": 0.6,
    }

    result = generate_hypotheses_node(state)
    assert result["status"] == "running"
    assert result["selected_hypothesis"] is not None
    assert result["selected_hypothesis"]["root_cause"] == "deployment_regression"
    assert result["selected_hypothesis"]["confidence"] >= 0.6
    assert set(result["selected_hypothesis"]["evidence_ids"]) == {id_deploy, id_metric, id_log}
    assert "summary" in result


def test_generate_hypotheses_node_insufficient_evidence_missing_deployment() -> None:
    state: IncidentAgentState = {
        "evidence_records": [
            {"id": str(uuid.uuid4()), "source_type": "metric"},
            {"id": str(uuid.uuid4()), "source_type": "log"},
        ],
        "signals": {
            "has_deployment": False,
            "has_error_logs": True,
            "has_metric_anomaly": True,
        },
        "min_confidence": 0.5,
    }

    result = generate_hypotheses_node(state)
    assert result["status"] == "insufficient_evidence"
    assert result["selected_hypothesis"] is None
    assert result["summary"] == "Insufficient evidence to determine a reliable root cause."


def test_generate_hypotheses_node_insufficient_evidence_missing_degradation() -> None:
    state: IncidentAgentState = {
        "evidence_records": [
            {"id": str(uuid.uuid4()), "source_type": "deployment"},
        ],
        "signals": {
            "has_deployment": True,
            "has_error_logs": False,
            "has_metric_anomaly": False,
        },
        "min_confidence": 0.5,
    }

    result = generate_hypotheses_node(state)
    assert result["status"] == "insufficient_evidence"
    assert result["selected_hypothesis"] is None


def test_generate_hypotheses_node_insufficient_evidence_below_min_confidence() -> None:
    id1 = str(uuid.uuid4())
    id2 = str(uuid.uuid4())
    state: IncidentAgentState = {
        "evidence_records": [
            {"id": id1, "source_type": "deployment"},
            {"id": id2, "source_type": "metric"},
        ],
        "signals": {
            "has_deployment": True,
            "has_metric_anomaly": True,
        },
        "min_confidence": 0.99,  # requires 99% confidence, which 2 records cannot meet
    }

    result = generate_hypotheses_node(state)
    assert result["status"] == "insufficient_evidence"
    assert result["selected_hypothesis"] is None
    assert "confidence threshold" in result["summary"]


def test_validate_grounding_node_success() -> None:
    ev_id1 = str(uuid.uuid4())
    ev_id2 = str(uuid.uuid4())
    state: IncidentAgentState = {
        "evidence_records": [{"id": ev_id1}, {"id": ev_id2}],
        "selected_hypothesis": {
            "root_cause": "deployment_regression",
            "evidence_ids": [ev_id1, ev_id2],
        },
    }

    result = validate_grounding_node(state)
    assert result["status"] == "running"
    assert result.get("grounding_validated") is True


def test_validate_grounding_node_no_hypothesis() -> None:
    state: IncidentAgentState = {
        "evidence_records": [{"id": str(uuid.uuid4())}],
        "selected_hypothesis": None,
    }

    result = validate_grounding_node(state)
    assert result["status"] == "insufficient_evidence"
    assert result["selected_hypothesis"] is None


def test_validate_grounding_node_empty_citations() -> None:
    state: IncidentAgentState = {
        "evidence_records": [{"id": str(uuid.uuid4())}],
        "selected_hypothesis": {
            "root_cause": "deployment_regression",
            "evidence_ids": [],
        },
    }

    result = validate_grounding_node(state)
    assert result["status"] == "insufficient_evidence"
    assert "zero evidence citations" in result["error_message"]
    assert result["selected_hypothesis"] is None


def test_validate_grounding_node_fake_evidence_id_rejected() -> None:
    real_id = str(uuid.uuid4())
    fake_id = str(uuid.uuid4())
    state: IncidentAgentState = {
        "evidence_records": [{"id": real_id}],
        "selected_hypothesis": {
            "root_cause": "deployment_regression",
            "evidence_ids": [real_id, fake_id],
        },
    }

    result = validate_grounding_node(state)
    assert result["status"] == "insufficient_evidence"
    assert result["selected_hypothesis"] is None
    assert "Hallucinated evidence IDs cited" in result["error_message"]
    assert fake_id in result["error_message"]


def test_propose_actions_node_with_hypothesis() -> None:
    incident_id = str(uuid.uuid4())
    state: IncidentAgentState = {
        "incident_id": incident_id,
        "selected_hypothesis": {"root_cause": "deployment_regression"},
        "retrieved_runbooks": [{"title": "Checkout DB Connection Exhaustion"}],
    }

    result = propose_actions_node(state)
    rec = result["selected_recommendation"]
    assert rec is not None
    assert rec["action_type"] == "simulated_rollback"
    assert rec["parameters"]["incident_id"] == incident_id
    assert rec["risk_level"] == RiskLevel.MEDIUM
    assert rec["requires_approval"] is True
    assert "Checkout DB Connection Exhaustion" in rec["rationale"]


def test_propose_actions_node_without_hypothesis() -> None:
    state: IncidentAgentState = {"selected_hypothesis": None}
    result = propose_actions_node(state)
    assert result["selected_recommendation"] is None
    assert result["recommendations"] == []


def test_safety_check_node_allowed_action() -> None:
    state: IncidentAgentState = {
        "selected_recommendation": {
            "action_type": "simulated_rollback",
            "requires_approval": True,
        }
    }

    result = safety_check_node(state)
    assert result["safety_check_passed"] is True
    assert result["requires_approval"] is True
    assert result["status"] == "completed"


def test_safety_check_node_disallowed_action() -> None:
    state: IncidentAgentState = {
        "selected_recommendation": {
            "action_type": "drop_production_database",
            "requires_approval": False,
        }
    }

    result = safety_check_node(state)
    assert result["safety_check_passed"] is False
    assert result["status"] == "failed"
    assert "not allowed" in result["error_message"]
    assert result["selected_recommendation"] is None


def test_safety_check_node_missing_recommendation() -> None:
    state: IncidentAgentState = {"selected_recommendation": None}

    result = safety_check_node(state)
    assert result["safety_check_passed"] is False
    assert result["status"] == "failed"
    assert "No recommendation provided" in result["error_message"]
