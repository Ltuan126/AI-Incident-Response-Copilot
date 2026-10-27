"""Backend safety policies and strict approval integrity enforcement.

Security invariants:
1. No mutating action can execute unless verified against a persisted, non-expired Approval record.
2. The decision must be strictly ApprovalStatus.APPROVED.
3. The action must be in ALLOWED_ACTIONS (allow-list).
4. The cryptographic SHA-256 action hash must match canonical parameters (tamper-proofing).
5. The approval must belong to the exact agent run executing it.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from apps.api.app.models.enums import ApprovalStatus
from apps.api.app.models.investigation import Approval

ALLOWED_ACTIONS = frozenset(
    {"simulated_restart", "simulated_rollback", "simulated_scale", "create_incident_note"}
)


class RemediationSecurityError(ValueError):
    """Raised when an action fails backend security, allowlist, or approval validation."""


def compute_action_hash(
    action_type: str, parameters: dict[str, Any], agent_run_id: uuid.UUID
) -> str:
    """Compute deterministic SHA-256 digest over action parameters and agent run ID."""
    canonical = json.dumps(
        {"action_type": action_type, "parameters": parameters, "agent_run_id": str(agent_run_id)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_backend_approval(
    approval: Approval | None,
    action_type: str,
    parameters: dict[str, Any],
    agent_run_id: uuid.UUID,
    now: datetime | None = None,
) -> None:
    """Strict backend verification before executing any mutating remediation tool.

    This check lives in Python code and database state, completely independent
    of whatever prompt or LLM instructions were provided.
    """
    if approval is None:
        raise RemediationSecurityError(
            f"MUTATING ACTION BLOCKED: No approval record exists for '{action_type}'."
        )

    # 1. Allowlist enforcement
    if action_type not in ALLOWED_ACTIONS:
        raise RemediationSecurityError(
            f"MUTATING ACTION BLOCKED: Action '{action_type}' is not in ALLOWED_ACTIONS."
        )

    # 2. Agent run ownership
    if approval.agent_run_id != agent_run_id:
        raise RemediationSecurityError(
            f"MUTATING ACTION BLOCKED: Approval {approval.id} belongs to run "
            f"{approval.agent_run_id}, not current run {agent_run_id}."
        )

    # 3. Status must be APPROVED
    if approval.status != ApprovalStatus.APPROVED:
        raise RemediationSecurityError(
            f"MUTATING ACTION BLOCKED: Approval status is '{approval.status}', must be 'approved'."
        )

    # 4. Expiration check
    current_time = now or datetime.now(UTC)
    expires_at = approval.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < current_time:
        raise RemediationSecurityError(
            f"MUTATING ACTION BLOCKED: Backend approval {approval.id} expired at {expires_at}."
        )

    # 5. Already executed check
    if approval.executed_at is not None:
        raise RemediationSecurityError(
            f"MUTATING ACTION BLOCKED: Approval {approval.id} has already been executed."
        )

    # 6. Action hash integrity (defends against parameter tampering / prompt injection)
    expected_hash = compute_action_hash(action_type, parameters, agent_run_id)
    if approval.action_hash != expected_hash:
        raise RemediationSecurityError(
            f"MUTATING ACTION BLOCKED: Action hash mismatch! Recorded '{approval.action_hash}', "
            f"calculated '{expected_hash}'. Parameters were tampered or do not match approval."
        )
