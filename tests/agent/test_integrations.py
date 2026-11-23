"""Unit Tests for NightShift Integrations: Slack Webhook & GitHub Sandbox PRs (Task B4).

Verifies:
1. Slack webhook client lifecycle, incident alerts, state transitions, and approvals.
2. Slack HTTP error handling and live URL mocking.
3. GitHub PR client lifecycle: create, get, comment, update, and close PR.
4. Structured remediation PR formatting with Evidence IDs and verification proof.
5. Documentation of 3 public stretch postmortems and 5 competitor analyses.
"""

from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from contracts.models import (
    Evidence,
    FixProposal,
    Hypothesis,
    Incident,
    VerificationResult,
)
from reporter.github_pr import GitHubPRClient, format_remediation_pr_body
from reporter.slack import SlackReporter


class TestIntegrations(unittest.TestCase):
    """Test suite for Slack Webhook and GitHub Sandbox PR integration."""

    def test_01_slack_reporter_initialization_and_mock_mode(self):
        """SlackReporter detects placeholder URLs and defaults to safe mock mode."""
        # Placeholder URL triggers mock mode
        reporter_default = SlackReporter()
        self.assertTrue(reporter_default.mock)

        # Explicit mock=False with live URL
        reporter_live = SlackReporter(
            webhook_url="https://hooks.slack.com/services/T00/B00/REALTOKEN123",
            mock=False,
        )
        self.assertFalse(reporter_live.mock)
        self.assertEqual(reporter_live.webhook_url, "https://hooks.slack.com/services/T00/B00/REALTOKEN123")

    def test_02_slack_reporter_message_types(self):
        """SlackReporter sends standard messages, incident alerts, state changes, and approval requests."""
        reporter = SlackReporter(mock=True)

        # 1. Send plain message
        res1 = reporter.send_message("Test message")
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["status"], "mock_delivered")

        # 2. Send Incident Alert
        inc = Incident(
            id="inc_test_01",
            service="orders",
            started_at="2026-11-22T21:40:00Z",
            symptoms=["500 error rate > 30%"],
            alerts=["Orders5xxHigh"],
        )
        res2 = reporter.send_incident_alert(inc)
        self.assertTrue(res2["ok"])
        self.assertIn("inc_test_01", res2["payload"]["text"])

        # 3. Send State Change
        res3 = reporter.send_state_change("inc_test_01", "open", "investigating", "Starting agent loop")
        self.assertTrue(res3["ok"])
        self.assertIn("investigating", res3["payload"]["text"])

        # 4. Send Approval Request
        proposal = FixProposal(
            type="rollback",
            risk_tier="T1",
            rationale="Roll back faulty deploy dep_v1",
            expected_metric_effect="Errors drop to 0%",
            target_service="orders",
        )
        res4 = reporter.send_approval_request("inc_test_01", proposal)
        self.assertTrue(res4["ok"])
        self.assertIn("T1", res4["payload"]["text"])

        self.assertEqual(len(reporter.sent_messages), 4)

    @patch("urllib.request.urlopen")
    def test_03_slack_reporter_live_http_and_error_handling(self, mock_urlopen):
        """SlackReporter dispatches HTTP POST in live mode and handles URLError gracefully."""
        # 1. Successful HTTP 200 response
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = b"ok"
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        reporter = SlackReporter(
            webhook_url="https://hooks.slack.com/services/T00/B00/VALIDTOKEN",
            mock=False,
        )
        res = reporter.send_message("Live test message")
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "delivered")

        # 2. HTTP Error handling
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        err_res = reporter.send_message("Fail message")
        self.assertFalse(err_res["ok"])
        self.assertEqual(err_res["status"], "error")
        self.assertIn("Connection refused", err_res["error"])

    def test_04_github_pr_client_mock_lifecycle(self):
        """GitHubPRClient creates, retrieves, comments on, updates, and closes PRs."""
        client = GitHubPRClient(mock=True)

        # 1. Create PR
        pr1 = client.create_or_update_pr(
            title="fix(orders): null check",
            body="Fixes incident inc_01",
            head_branch="nightshift/fix-inc-01",
            base_branch="main",
        )
        pr_number = pr1["number"]
        self.assertEqual(pr1["state"], "open")
        self.assertEqual(pr1["head"]["ref"], "nightshift/fix-inc-01")

        # 2. Retrieve PR
        fetched = client.get_pr(pr_number)
        self.assertEqual(fetched["title"], "fix(orders): null check")

        # 3. Add comment
        comment = client.add_comment(pr_number, "Canary test passed.")
        self.assertEqual(comment["id"], 1)
        self.assertEqual(client.get_pr(pr_number)["comments_count"], 1)

        # 4. Update PR on same branch without creating duplicate
        pr_updated = client.create_or_update_pr(
            title="fix(orders): null check v2",
            body="Updated fix body",
            head_branch="nightshift/fix-inc-01",
            base_branch="main",
        )
        self.assertEqual(pr_updated["number"], pr_number)
        self.assertEqual(pr_updated["title"], "fix(orders): null check v2")

        # 5. Close PR
        pr_closed = client.close_pr(pr_number)
        self.assertEqual(pr_closed["state"], "closed")
        self.assertIsNotNone(pr_closed["closed_at"])

    def test_05_format_remediation_pr_body(self):
        """format_remediation_pr_body produces structured markdown with all 4 required sections."""
        inc = Incident(
            id="inc_20261122_001",
            service="orders",
            started_at="2026-11-22T21:40:00Z",
            symptoms=["Spike in 500 errors"],
        )
        hyp = Hypothesis(
            cause="Deployment v1 introduced TypeError in create_order [ev_log_001].",
            category="code",
            confidence=0.95,
            evidence_ids=["ev_log_001"],
            culprit_change="dep_v1",
        )
        prop = FixProposal(
            type="patch",
            diff="--- a/main.py\n+++ b/main.py\n",
            risk_tier="T2",
            rationale="Guard discount key",
            expected_metric_effect="500s drop to 0%",
        )
        verif = VerificationResult(
            tests_passed=True,
            repro_fixed=True,
            canary_healthy=True,
            metric_before=0.35,
            metric_after=0.005,
            verdict="PASS",
        )

        pr_markdown = format_remediation_pr_body(inc, hyp, prop, verif)

        # Verify Section 7 & Day 4 B4 components
        self.assertIn("inc_20261122_001", pr_markdown)
        self.assertIn("[ev_log_001]", pr_markdown)
        self.assertIn("dep_v1", pr_markdown)
        self.assertIn("Guard discount key", pr_markdown)
        self.assertIn("500s drop to 0%", pr_markdown)
        self.assertIn("PASS", pr_markdown)
        self.assertIn("35.0%", pr_markdown)
        self.assertIn("0.5%", pr_markdown)

    def test_06_stretch_postmortems_file(self):
        """docs/stretch_postmortems.md documents Cloudflare 2019, AWS DynamoDB 2015, and GitLab 2017."""
        doc_path = Path(__file__).resolve().parent.parent.parent / "docs" / "stretch_postmortems.md"
        self.assertTrue(doc_path.exists(), f"File {doc_path} must exist.")
        content = doc_path.read_text(encoding="utf-8")

        self.assertIn("Cloudflare", content)
        self.assertIn("July 2, 2019", content)
        self.assertIn("fault_021_cloudflare_regex_cpu", content)

        self.assertIn("DynamoDB", content)
        self.assertIn("September 20, 2015", content)
        self.assertIn("fault_022_aws_dynamodb_lease_split_brain", content)

        self.assertIn("GitLab", content)
        self.assertIn("January 31, 2017", content)
        self.assertIn("fault_023_repeated_incident_memory", content)

    def test_07_competitor_analysis_file(self):
        """docs/competitor_analysis.md and pitch/competitors.md document 5 competitors."""
        doc_path = Path(__file__).resolve().parent.parent.parent / "docs" / "competitor_analysis.md"
        self.assertTrue(doc_path.exists(), f"File {doc_path} must exist.")
        content = doc_path.read_text(encoding="utf-8")

        competitors = ["K8sGPT", "PagerDuty", "Datadog Bits", "Rootly", "Devin"]
        for comp in competitors:
            self.assertIn(comp, content)

        pitch_path = Path(__file__).resolve().parent.parent.parent / "pitch" / "competitors.md"
        self.assertTrue(pitch_path.exists(), f"File {pitch_path} must exist.")


if __name__ == "__main__":
    unittest.main()
