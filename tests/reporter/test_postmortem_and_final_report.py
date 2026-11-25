"""Unit tests for PostmortemGenerator & FinalReportPublisher (Day 7 Tasks B3 & B4).

Verifies:
1. Task B3: 3 postmortems pass the 6-section checklist and every claim cites an evidence ID.
2. Task B4: Final Slack and PR report contains all 6 parts, recovery graph SVG, and all links resolve.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contracts.models import Evidence, FixProposal, Hypothesis, Incident, VerificationResult
from reporter import (
    FinalReportPublisher,
    GitHubPRClient,
    PostmortemGenerator,
    SlackReporter,
)


class TestPostmortemAndFinalReport(unittest.TestCase):
    """Test suite for Day 7 Tasks B3 and B4."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)
        self.pm_gen = PostmortemGenerator()
        self.publisher = FinalReportPublisher(postmortem_generator=self.pm_gen)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_three_postmortems_pass_checklist_and_every_claim_has_evidence_id(self) -> None:
        """Exit criterion B3: 3 postmortems checked against checklist; every claim has an evidence ID."""
        scenarios = [
            (
                "fault_001_bad_deploy",
                "orders",
                "TypeError: 'NoneType' object is not subscriptable in create_order",
                "code",
                "patch",
                "T2",
                [Evidence(id="ev_log_001", type="log", ref="orders/app.py:82", excerpt="TypeError at orders/app.py:82", ts="2026-11-25T12:00:00Z")],
            ),
            (
                "fault_015_disk_full",
                "orders",
                "Unrotated DEBUG logging filled partition to 100%",
                "resource",
                "config",
                "T1",
                [Evidence(id="ev_metric_015", type="metric", ref="prom:disk_usage_pct", excerpt="disk_usage_pct=100%", ts="2026-11-25T12:00:00Z")],
            ),
            (
                "fault_017_symptom_gw_cause_payments",
                "payments",
                "Validation failure in payments cascaded HTTP 502 to gateway",
                "cross_service",
                "patch",
                "T2",
                [Evidence(id="ev_trace_017", type="log", ref="payments/app.py:45", excerpt="payments validation 502", ts="2026-11-25T12:00:00Z")],
            ),
        ]

        for idx, (fid, svc, cause, cat, ftype, tier, evs) in enumerate(scenarios, 1):
            with self.subTest(fault_id=fid):
                inc = Incident(
                    id=f"inc_pm_{idx}",
                    service=svc,
                    started_at="2026-11-25T12:00:00Z",
                    symptoms=[f"Anomaly for {fid}"],
                    alerts=[f"Alert_{fid}"],
                )
                hyp = Hypothesis(
                    cause=cause,
                    category=cat,
                    confidence=0.93,
                    evidence_ids=[evs[0].id],
                )
                prop = FixProposal(
                    type=ftype,
                    diff=f"diff --git a/target-app/services/{svc}/app.py b/target-app/services/{svc}/app.py\n",
                    risk_tier=tier,
                    rationale=f"Remediate {cause}",
                    expected_metric_effect="Error rate drops below 1%",
                    target_service=svc,
                )
                ver = VerificationResult(
                    tests_passed=True,
                    repro_fixed=True,
                    canary_healthy=True,
                    metric_before=0.25,
                    metric_after=0.002,
                    recovered_at="2026-11-25T12:02:00Z",
                    verdict="PASS",
                )

                report = self.pm_gen.generate(
                    inc,
                    fault_id=fid,
                    hypothesis=hyp,
                    proposal=prop,
                    verification=ver,
                    evidence_items=evs,
                )
                checklist = self.pm_gen.validate_checklist(report)

                self.assertTrue(checklist["has_timeline"])
                self.assertTrue(checklist["has_cause"])
                self.assertTrue(checklist["has_evidence"])
                self.assertTrue(checklist["has_fix"])
                self.assertTrue(checklist["has_verification"])
                self.assertTrue(checklist["has_follow_ups"])
                self.assertTrue(checklist["all_claims_cite_evidence_id"])
                self.assertTrue(checklist["passed"], f"Checklist failed for {fid}: {checklist}")

                md_path = self.pm_gen.save_markdown(report, self.out_dir / f"pm_{idx}.md")
                self.assertTrue(md_path.exists())
                md_text = md_path.read_text(encoding="utf-8")
                self.assertIn("## 1. Timeline", md_text)
                self.assertIn("## 6. Follow-up Actions", md_text)

    def test_02_final_slack_and_pr_report_contains_all_six_parts_and_links_resolve(self) -> None:
        """Exit criterion B4: Final report contains all 6 parts, recovery graph, and resolving links."""
        inc = Incident(
            id="inc_final_001",
            service="orders",
            started_at="2026-11-25T12:10:00Z",
            symptoms=["HTTP 500 spike to 22% on POST /orders"],
            alerts=["OrdersHigh5xxRate"],
        )
        hyp = Hypothesis(
            cause="Missing null guard on optional discount object",
            category="code",
            confidence=0.95,
            evidence_ids=["ev_log_f1"],
        )
        prop = FixProposal(
            type="patch",
            diff="diff --git a/target-app/services/orders/app.py b/target-app/services/orders/app.py\n",
            risk_tier="T2",
            rationale="Guard discount.get('code') when discount is None",
            expected_metric_effect="Error rate drops from 22% to < 1%",
            target_service="orders",
        )
        ver = VerificationResult(
            tests_passed=True,
            repro_fixed=True,
            canary_healthy=True,
            metric_before=0.22,
            metric_after=0.002,
            recovered_at="2026-11-25T12:12:00Z",
            verdict="PASS",
        )

        slack = SlackReporter(mock=True)
        pr_client = GitHubPRClient(mock=True)

        result = self.publisher.publish(
            incident=inc,
            fault_id="fault_001_bad_deploy",
            hypothesis=hyp,
            proposal=prop,
            verification=ver,
            slack_reporter=slack,
            pr_client=pr_client,
            out_dir=self.out_dir / "final_reports",
            evidence_items=[Evidence(id="ev_log_f1", type="log", ref="orders/app.py:82", excerpt="TypeError in orders/app.py", ts="2026-11-25T12:10:00Z")],
        )

        # Verify all 6 sections are present in both Markdown PR comment and Slack message
        self.assertEqual(len(result.sections_present), 6)
        for heading in (
            "### 1. Timeline",
            "### 2. Root Cause",
            "### 3. Evidence",
            "### 4. Remediation Fix & PR",
            "### 5. Verification & Recovery Graph",
            "### 6. Follow-ups & Postmortem",
        ):
            self.assertIn(heading, result.markdown_report)

        for marker in (
            "1. *Timeline:*",
            "2. *Root Cause:*",
            "3. *Evidence:*",
            "4. *Fix & PR:*",
            "5. *Verification & Recovery Graph:*",
            "6. *Follow-ups & Postmortem:*",
        ):
            self.assertIn(marker, result.slack_text)

        # Verify Slack delivery and PR comment delivery
        self.assertTrue(result.slack_response["ok"])
        self.assertEqual(len(slack.sent_messages), 1)
        self.assertEqual(len(pr_client._mock_comments[result.pr_number]), 1)

        # Verify all links resolve
        self.assertTrue(result.pr_url.startswith("https://github.com/"))
        self.assertIn(result.pr_number, pr_client._mock_prs)
        self.assertTrue(result.recovery_graph_path.exists())
        self.assertIn("<svg", result.recovery_graph_path.read_text(encoding="utf-8"))
        self.assertTrue(result.postmortem_path.exists())
        self.assertIn("## 1. Timeline", result.postmortem_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
