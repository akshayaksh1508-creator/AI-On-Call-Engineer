"""Day 4 remediation PR content and idempotency checks."""

import unittest
from unittest.mock import patch

from contracts.models import FixProposal, Hypothesis, Incident, VerificationResult
from reporter.github_pr import GitHubPRClient, format_remediation_pr_body


class GitHubPRDay4Tests(unittest.TestCase):
    def setUp(self):
        self.incident = Incident(
            id="inc-1", service="orders", started_at="2026-01-01T00:00:00Z",
            symptoms=["500 spike"],
        )
        self.hypothesis = Hypothesis(
            cause="Unsafe null access", category="code", confidence=0.9,
            evidence_ids=["ev-log-1"], culprit_change="dep-1",
        )
        self.proposal = FixProposal(
            type="patch", diff="diff", risk_tier="T2", rationale="Guard null",
            expected_metric_effect="Error rate returns under 1%",
        )

    def test_pr_body_contains_all_day4_sections_and_test_verdict(self):
        verification = VerificationResult(
            tests_passed=True, repro_fixed=True, canary_healthy=False,
            metric_before=0.2, metric_after=0.0, verdict="FAIL",
        )
        body = format_remediation_pr_body(
            self.incident, self.hypothesis, self.proposal, verification
        )
        for required in ("Unsafe null access", "ev-log-1", "Error rate returns under 1%", "FAIL", "REPRO FIXED"):
            self.assertIn(required, body)

    def test_mock_retries_update_one_open_pr(self):
        client = GitHubPRClient(mock=True, repo="owner/sandbox")
        first = client.create_remediation_pr(
            self.incident, self.hypothesis, self.proposal, "fix/inc-1"
        )
        second = client.create_remediation_pr(
            self.incident, self.hypothesis, self.proposal.model_copy(update={"rationale": "Improved guard"}),
            "fix/inc-1",
        )
        self.assertEqual(first["number"], second["number"])
        self.assertEqual(len(client._mock_prs), 1)
        self.assertIn("Improved guard", second["body"])

    def test_live_retry_finds_and_updates_existing_pr(self):
        client = GitHubPRClient(token="token", repo="owner/sandbox", mock=False)
        calls = []

        def fake_request(url, method="GET", payload=None):
            calls.append((url, method, payload))
            if method == "GET":
                return [{"number": 17}]
            return {"number": 17, **(payload or {})}

        with patch.object(client, "_http_request", side_effect=fake_request):
            result = client.create_or_update_pr("title", "body", "fix/inc-1")
        self.assertEqual(result["number"], 17)
        self.assertEqual([call[1] for call in calls], ["GET", "PATCH"])
        self.assertIn("head=owner%3Afix%2Finc-1", calls[0][0])


if __name__ == "__main__":
    unittest.main()
