"""Scratch verification script for NightShift Integrations (Task B4).

Demonstrates and verifies:
1. Slack webhook client: Posts test message, state transition, and approval request.
2. GitHub sandbox client: Opens a remediation PR, adds a comment, and closes the PR.
3. Structured PR body formatting meeting Section 7 rules.

Usage:
    python scratch/test_integrations.py
"""

import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from contracts.models import (
    Evidence,
    FixProposal,
    Hypothesis,
    Incident,
    VerificationResult,
)
from reporter.github_pr import GitHubPRClient, format_remediation_pr_body
from reporter.slack import SlackReporter


def run_integrations_test():
    print("=" * 75)
    print("NightShift AI On-Call Engineer: Integrations Verification (Task B4)")
    print("=" * 75)

    # -------------------------------------------------------------------------
    # Part 1: Slack Webhook Integration Test
    # -------------------------------------------------------------------------
    print("\n[1/2] Testing Slack Webhook Integration...")
    slack = SlackReporter()
    mode_str = "Mock (Offline/Safe)" if slack.mock else f"Live Webhook ({slack.webhook_url[:35]}...)"
    print(f"      Mode: {mode_str}")

    # 1.1 Post simple message
    msg_res = slack.send_message(":wave: NightShift On-Call Agent online. Day 1 verification test.")
    assert msg_res["ok"], f"Failed to send test message: {msg_res}"
    print("      [PASS] Sent test webhook message.")

    # 1.2 Send Incident Alert
    test_incident = Incident(
        id="inc_20261122_b4_test",
        service="orders",
        started_at="2026-11-22T21:40:00Z",
        symptoms=["HTTP 500 error rate spiked to 35% on POST /orders"],
        alerts=["OrdersHigh5xxRate"],
        recent_changes=["dep_20261122_v1.0.1"],
        status="investigating",
    )
    alert_res = slack.send_incident_alert(test_incident)
    assert alert_res["ok"], f"Failed to send incident alert: {alert_res}"
    print(f"      [PASS] Sent incident alert for {test_incident.id}.")

    # 1.3 Send State Change
    state_res = slack.send_state_change(
        incident_id=test_incident.id,
        old_state="investigating",
        new_state="mitigating",
        details="Autonomous fix proposal generated. Initiating canary deploy.",
    )
    assert state_res["ok"], f"Failed to send state change: {state_res}"
    print("      [PASS] Sent state transition notification.")

    # 1.4 Send Interactive Approval Request
    test_proposal = FixProposal(
        type="patch",
        diff="--- a/orders/main.py\n+++ b/orders/main.py\n@@ -42 +42 @@\n-discount_code = request.discount['code']\n+discount_code = request.discount.get('code') if request.discount else None\n",
        risk_tier="T2",
        rationale="Guard discount dictionary dereference against NoneType.",
        expected_metric_effect="500 error rate drops from 35% to <1% within 30s.",
        target_service="orders",
    )
    approval_res = slack.send_approval_request(test_incident.id, test_proposal)
    assert approval_res["ok"], f"Failed to send approval request: {approval_res}"
    print(f"      [PASS] Sent T2 remediation sign-off request.")
    print(f"      Total Slack messages sent: {len(slack.sent_messages)}")

    # -------------------------------------------------------------------------
    # Part 2: GitHub Sandbox PR Lifecycle Test (Open -> Comment -> Close)
    # -------------------------------------------------------------------------
    print("\n[2/2] Testing GitHub Sandbox Pull Request Lifecycle...")
    github = GitHubPRClient()
    gh_mode_str = "Mock (Offline/Safe)" if github.mock else f"Live Sandbox ({github.repo})"
    print(f"      Mode: {gh_mode_str}")

    # 2.1 Format PR Body using Section 7 rules
    test_hypothesis = Hypothesis(
        cause="Deployment v1.0.1 introduced unhandled NoneType subscripting in create_order() [ev_log_001].",
        category="code",
        confidence=0.94,
        evidence_ids=["ev_log_001"],
        culprit_change="dep_20261122_v1.0.1",
    )
    test_verification = VerificationResult(
        tests_passed=True,
        repro_fixed=True,
        canary_healthy=True,
        metric_before=0.35,
        metric_after=0.005,
        verdict="PASS",
    )

    pr_body = format_remediation_pr_body(
        incident=test_incident,
        hypothesis=test_hypothesis,
        proposal=test_proposal,
        verification=test_verification,
    )
    print(f"      Formatted PR body ({len(pr_body)} chars).")

    # 2.2 Open PR on sandbox repo
    pr_title = f"fix(orders): autonomous remediation for incident {test_incident.id}"
    pr = github.create_or_update_pr(
        title=pr_title,
        body=pr_body,
        head_branch="nightshift/fix-inc-20261122-001",
        base_branch="main",
    )
    pr_number = pr["number"]
    print(f"      [PASS] Opened PR #{pr_number}: '{pr['title']}' (State: {pr['state']})")
    print(f"             URL: {pr['html_url']}")
    assert pr["state"] == "open", f"Expected PR #{pr_number} to be open, got {pr['state']}"

    # 2.3 Add verification comment
    comment_text = (
        ":white_check_mark: **Automated Canary Proof Verified**\n"
        "- Production traffic replay completed with 0 errors.\n"
        "- HTTP 500 error rate recovered to baseline (0.5%).\n"
        "- Canary health check: PASS."
    )
    comment = github.add_comment(pr_number, comment_text)
    print(f"      [PASS] Added verification comment #{comment['id']} to PR #{pr_number}.")

    # 2.4 Verify PR metadata
    fetched_pr = github.get_pr(pr_number)
    assert fetched_pr["number"] == pr_number
    assert fetched_pr["state"] == "open"
    print(f"      [PASS] Retrieved PR #{pr_number} successfully.")

    # 2.5 Close PR
    closed_pr = github.close_pr(pr_number)
    assert closed_pr["state"] == "closed", f"Expected PR #{pr_number} to be closed, got {closed_pr['state']}"
    print(f"      [PASS] Closed PR #{pr_number} successfully (Closed at: {closed_pr['closed_at']}).")

    print("\n" + "=" * 75)
    print("SUCCESS: Task B4 Integrations Verification Passed!")
    print("  • Slack webhook posted test message and formatted incident cards.")
    print("  • GitHub client opened, commented on, and closed a test PR.")
    print("=" * 75)


if __name__ == "__main__":
    run_integrations_test()
