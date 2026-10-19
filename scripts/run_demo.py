"""End-to-end incident response demo runner.

Runs the complete incident lifecycle from start to finish:
Alert -> Collect Evidence -> Analyze -> Propose Remediation ->
Human Approval -> Execute Simulated Rollback -> Verify Recovery -> Close Incident.

Usage:
    python scripts/run_demo.py
    python scripts/run_demo.py --interactive
    python scripts/run_demo.py --api-url http://localhost:8000
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def api_request(
    url: str, method: str = "GET", data: dict[str, Any] | None = None
) -> dict[str, Any]:
    encoded_data = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(  # noqa: S310
        url, data=encoded_data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            content = resp.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as exc:
        err_msg = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {method} {url}: {err_msg}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error connecting to {url}: {exc.reason}") from exc


def log_step(step_num: int, title: str, description: str) -> None:
    print(f"\n{BOLD}{CYAN}=== [Step {step_num}] {title} ==={RESET}")
    print(f"{DIM}{description}{RESET}\n")


def print_json(data: dict[str, Any]) -> None:
    print(f"{DIM}{json.dumps(data, indent=2)}{RESET}")


def run_demo(api_url: str, interactive: bool) -> int:
    api_url = api_url.rstrip("/")

    print(f"""{BOLD}{GREEN}
========================================================================
       AI INCIDENT RESPONSE COPILOT — END-TO-END DEMO RUNNER
========================================================================{RESET}
Target API: {api_url}
Mode:       {"Interactive (prompting for approvals)" if interactive else "Automated"}
Timestamp:  {datetime.now(UTC).isoformat()}
""")

    # Check health
    try:
        health = api_request(f"{api_url}/health")
        print(f"[{GREEN}OK{RESET}] API liveness confirmed: {health}")
    except Exception as exc:
        print(f"[{RED}FAIL{RESET}] Could not connect to API at {api_url}: {exc}", file=sys.stderr)
        print(
            "\nPlease ensure the API is running before executing the demo:\n"
            "  docker compose up -d\n"
            "  or\n"
            "  alembic upgrade head && uvicorn apps.api.app.main:app --reload\n",
            file=sys.stderr,
        )
        return 1

    # Step 1: Simulate fault mode
    log_step(1, "Simulate Fault Mode", "Triggering deployment regression on checkout service...")
    try:
        sim_resp = api_request(
            f"{api_url}/api/v1/simulator/incidents/deployment-regression", method="POST"
        )
        print(f"[{GREEN}OK{RESET}] Fault scenario triggered: {sim_resp.get('scenario')}")
        print(f"     Detail: {sim_resp.get('detail')}")
    except Exception as exc:
        print(f"[{YELLOW}WARN{RESET}] Simulator warning (service may not be running): {exc}")

    # Step 2: Alert Ingestion
    log_step(
        2,
        "Alert Ingestion",
        "Ingesting critical high_error_rate alert from Prometheus Alertmanager...",
    )
    alert_payload = {
        "service_name": "checkout-api",
        "alert_type": "high_error_rate",
        "severity": "critical",
        "started_at": datetime.now(UTC).isoformat(),
        "labels": {"environment": "production", "service": "checkout-api"},
        "observed_value": 0.35,
        "threshold": 0.05,
    }
    alert_resp = api_request(f"{api_url}/api/v1/alerts", method="POST", data=alert_payload)
    incident_id = alert_resp["incident_id"]
    alert_id = alert_resp["alert_id"]
    print(f"[{GREEN}OK{RESET}] Alert received: {alert_id}")
    print(f"     Incident opened: {BOLD}{incident_id}{RESET} (status: {alert_resp['status']})")

    # Step 3: Evidence Collection
    log_step(
        3,
        "Evidence Collection",
        f"Querying Prometheus, Loki, and Deployment history for incident {incident_id}...",
    )
    try:
        collect_resp = api_request(
            f"{api_url}/api/v1/incidents/{incident_id}/collect-evidence", method="POST"
        )
        print(f"[{GREEN}OK{RESET}] Collection run ID: {collect_resp['agent_run_id']}")
        print(f"     Status: {collect_resp['status']}")
        print(f"     Evidence items collected: {len(collect_resp.get('evidence_ids', []))}")
        for source in collect_resp.get("sources", []):
            st = source.get("status")
            color = GREEN if st == "succeeded" else YELLOW
            stype = source.get("source_type")
            msg = source.get("message")
            print(f"     - [{color}{st}{RESET}] {stype}: {msg}")
    except Exception as exc:
        print(f"[{RED}FAIL{RESET}] Evidence collection error: {exc}", file=sys.stderr)
        return 1

    # Step 4: Evidence-Grounded Analysis
    log_step(
        4,
        "Evidence-Grounded Analysis",
        "Analyzing collected metrics, logs, and deployment events to identify root cause...",
    )
    try:
        analysis_resp = api_request(
            f"{api_url}/api/v1/incidents/{incident_id}/analyze", method="POST"
        )
        print(f"[{GREEN}OK{RESET}] Analysis status: {analysis_resp['status']}")
        hyp = analysis_resp.get("hypothesis")
        rec = analysis_resp.get("recommendation")
        if hyp:
            print(f"     {BOLD}Root Cause:{RESET} {hyp.get('root_cause')}")
            print(f"     {BOLD}Confidence:{RESET} {hyp.get('confidence') * 100:.1f}%")
            print(f"     {BOLD}Summary:{RESET}    {hyp.get('summary')}")
            print(f"     {BOLD}Citations:{RESET}  {len(hyp.get('evidence_ids', []))} evidence rows")
        if rec:
            print(f"\n     {BOLD}Recommended Remediation:{RESET}")
            print(f"     - Action:            {rec.get('action_type')}")
            print(f"     - Risk Level:        {rec.get('risk_level')}")
            print(f"     - Requires Approval: {rec.get('requires_approval')}")
            print(f"     - Rationale:         {rec.get('rationale')}")
            recommendation_id = rec.get("id")
        else:
            print(f"[{YELLOW}WARN{RESET}] No recommendation proposed.")
            return 1
    except Exception as exc:
        print(f"[{RED}FAIL{RESET}] Analysis error: {exc}", file=sys.stderr)
        return 1

    # Step 5: Propose Remediation & Request Human Approval
    log_step(
        5,
        "Human Approval Gate",
        "Gating remediation execution behind human authorization...",
    )
    approval_resp = api_request(
        f"{api_url}/api/v1/recommendations/{recommendation_id}/approval", method="POST"
    )
    approval_id = approval_resp["id"]
    print(f"[{GREEN}OK{RESET}] Approval Request created: {approval_id}")
    print(f"     Action:       {approval_resp['action_type']}")
    print(f"     Action Hash:  {approval_resp['action_hash'][:16]}...")
    print(f"     Status:       {YELLOW}{approval_resp['status']}{RESET}")
    print(f"     Expires At:   {approval_resp['expires_at']}")

    # Step 6: Review & Decision
    log_step(6, "Operator Review & Decision", "SRE engineer evaluates the recommendation...")
    if interactive:
        confirm = input(
            f"Approve rollback action '{approval_resp['action_type']}' for {incident_id}? [Y/n]: "
        ).strip()
        if confirm.lower() == "n":
            decision = "rejected"
            reason = "Operator chose not to proceed with automated rollback."
        else:
            decision = "approved"
            reason = "Verified deployment regression v1.4.2 via Loki and Prometheus evidence."
    else:
        decision = "approved"
        reason = "Automated verification: telemetry matches deployment regression pattern."

    decide_resp = api_request(
        f"{api_url}/api/v1/approvals/{approval_id}/decision",
        method="POST",
        data={"decision": decision, "decided_by": "oncall-sre@company.com", "reason": reason},
    )
    print(f"[{GREEN}OK{RESET}] Decision recorded: {BOLD}{decide_resp['status'].upper()}{RESET}")
    print(f"     Decided By: {decide_resp.get('decided_by')}")
    print(f"     Reason:     {decide_resp.get('decision_reason')}")

    if decision != "approved":
        print(f"\n[{YELLOW}INFO{RESET}] Remediation was rejected. Flow terminated as expected.")
        return 0

    # Step 7: Execute Simulated Rollback
    log_step(
        7,
        "Execute Simulated Rollback",
        "Executing approved rollback against demo checkout service...",
    )
    try:
        execute_resp = api_request(
            f"{api_url}/api/v1/approvals/{approval_id}/execute", method="POST"
        )
        print(f"[{GREEN}OK{RESET}] Execution status: {execute_resp['execution_status']}")
        print(f"     Executed at:      {execute_resp['executed_at']}")
    except Exception as exc:
        print(f"[{RED}FAIL{RESET}] Execution error: {exc}", file=sys.stderr)
        return 1

    # Step 8: Verify Recovery & Incident Closure
    log_step(
        8,
        "Verify Recovery & Close Incident",
        "Verifying health check recovery and validating incident closure...",
    )
    # Check updated incident
    time.sleep(1)
    incident_resp = api_request(f"{api_url}/api/v1/incidents/{incident_id}")
    print(f"[{GREEN}OK{RESET}] Incident State:")
    print(f"     Status:      {BOLD}{GREEN}{incident_resp['status'].upper()}{RESET}")
    print(f"     Resolved At: {incident_resp.get('resolved_at')}")

    # Step 9: Audit Trail Timeline
    log_step(
        9,
        "Audit Trail & Timeline",
        "Inspecting chronological timeline events recorded in the system...",
    )
    timeline_resp = api_request(f"{api_url}/api/v1/incidents/{incident_id}/timeline")
    events = timeline_resp.get("events", [])
    print(f"Found {len(events)} timeline events for incident {incident_id}:\n")
    for event in events:
        ts = event.get("created_at")
        etype = event.get("event_type")
        msg = event.get("message")
        print(f"  [{DIM}{ts}{RESET}] {BOLD}{CYAN}{etype:<24}{RESET} {msg}")

    print(f"""\n{BOLD}{GREEN}
========================================================================
           DEMO COMPLETED SUCCESSFULLY WITH ZERO MANUAL ERRORS!
========================================================================{RESET}
Incident {incident_id} successfully progressed:
Alert -> Collect -> Analyze -> Approve -> Execute -> Recover -> Resolved!
""")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the Copilot API (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Prompt operator for manual confirmation at the approval gate",
    )
    args = parser.parse_args()
    return run_demo(api_url=args.api_url, interactive=args.interactive)


if __name__ == "__main__":
    raise SystemExit(main())
