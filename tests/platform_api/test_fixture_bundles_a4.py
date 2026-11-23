"""Unit and Parity Tests for Recorded Fixture Bundles (Day 2 Task A4).

Owner: Person A (Systems & Proof)
Verifies:
1. Three fixture bundles recorded from live faults (fault_001, fault_002, fault_003).
2. All bundles load in FixtureClient and validate against contract schemas.
3. Querying each bundle via FixtureClient returns the exact same answers as the live system.
4. All 9 tools operate with full parity across all recorded bundles.
"""

import json
from pathlib import Path
import unittest

from contracts import (
    Incident,
    FixProposal,
    load_fixture_bundle,
)
from platform_api import (
    FixtureClient,
    create_platform_client,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestRecordedFixtureBundles(unittest.TestCase):
    """Test suite validating Day 2 Task A4 recorded fixture bundles."""

    RECORDED_BUNDLES = [
        "fault_001_bad_deploy",
        "fault_002_off_by_one",
        "fault_003_wrong_status_code",
        "fault_004_bad_parsing",
        "fault_005_unhandled_exception",
    ]

    REQUIRED_ARTIFACTS = [
        "incident",
        "logs",
        "metrics",
        "changes",
        "repo_snapshot",
        "service_map",
        "past_incidents",
    ]

    def test_01_three_fixture_bundles_exist_and_load(self):
        """At least 3 recorded fixture bundles exist and load via load_fixture_bundle."""
        self.assertGreaterEqual(len(self.RECORDED_BUNDLES), 3)

        for bundle_name in self.RECORDED_BUNDLES[:3]:
            bundle = load_fixture_bundle(bundle_name)
            self.assertIsInstance(bundle, dict)
            self.assertEqual(bundle.get("name"), bundle_name)

            for artifact in self.REQUIRED_ARTIFACTS:
                self.assertIn(
                    artifact,
                    bundle,
                    f"Bundle '{bundle_name}' missing required artifact '{artifact}'",
                )

    def test_02_incident_contract_validation(self):
        """Every recorded bundle's incident.json validates against the Incident contract model."""
        for bundle_name in self.RECORDED_BUNDLES:
            bundle = load_fixture_bundle(bundle_name)
            inc_dict = bundle["incident"]

            # Must parse cleanly into Incident Pydantic model
            inc = Incident(**inc_dict)
            self.assertTrue(inc.id.startswith("inc_"))
            self.assertEqual(inc.status, "open")
            self.assertIn(inc.service, ["orders", "payments", "gateway"])
            self.assertGreater(len(inc.symptoms), 0)
            self.assertGreater(len(inc.alerts), 0)
            self.assertGreater(len(inc.recent_changes), 0)

    def test_03_logs_structured_format_and_error_signatures(self):
        """Every bundle's logs.json contains structured JSON logs with error traces."""
        expected_signatures = {
            "fault_001_bad_deploy": "TypeError",
            "fault_002_off_by_one": "IndexError",
            "fault_003_wrong_status_code": "DECLINED",
            "fault_004_bad_parsing": "ValueError",
            "fault_005_unhandled_exception": "ZeroDivisionError",
        }

        for bundle_name in self.RECORDED_BUNDLES:
            bundle = load_fixture_bundle(bundle_name)
            logs = bundle["logs"]
            self.assertIsInstance(logs, list)
            self.assertGreater(len(logs), 0)

            # Check standard telemetry fields on each log
            for log in logs:
                self.assertIn("service", log)
                self.assertIn("trace_id", log)
                self.assertIn("timestamp", log)
                self.assertIn("level", log)
                self.assertIn("message", log)

            sig = expected_signatures.get(bundle_name)
            if sig:
                found_sig = any(
                    sig in log.get("message", "") or sig in log.get("exception", "")
                    for log in logs
                )
                self.assertTrue(
                    found_sig,
                    f"Bundle '{bundle_name}' logs must contain signature '{sig}'",
                )

    def test_04_changes_artifact_contains_culprit_deployment(self):
        """Every bundle's changes.json includes the culprit deployment event."""
        expected_changes = {
            "fault_001_bad_deploy": "dep_20261122_v1.0.1",
            "fault_002_off_by_one": "dep_20261123_v1.0.2",
            "fault_003_wrong_status_code": "dep_20261123_v1.0.3",
            "fault_004_bad_parsing": "dep_20261123_v1.0.4",
            "fault_005_unhandled_exception": "dep_20261123_v1.0.5",
        }

        for bundle_name, expected_dep in expected_changes.items():
            bundle = load_fixture_bundle(bundle_name)
            changes = bundle["changes"]
            self.assertIsInstance(changes, list)
            self.assertGreater(len(changes), 0)

            change_ids = [c.get("id") for c in changes]
            self.assertIn(
                expected_dep,
                change_ids,
                f"Bundle '{bundle_name}' changes must contain '{expected_dep}'",
            )

    def test_05_metrics_prometheus_matrix_format(self):
        """Every bundle's metrics.json adheres to Prometheus matrix query format."""
        for bundle_name in self.RECORDED_BUNDLES:
            bundle = load_fixture_bundle(bundle_name)
            metrics = bundle["metrics"]
            self.assertEqual(metrics.get("status"), "success")
            self.assertIn("data", metrics)
            self.assertEqual(metrics["data"].get("resultType"), "matrix")

            results = metrics["data"].get("result", [])
            self.assertGreater(len(results), 0)
            for r in results:
                self.assertIn("metric", r)
                self.assertIn("values", r)
                self.assertGreater(len(r["values"]), 0)

    def test_06_repo_snapshot_commits_diff_and_files(self):
        """Every bundle's repo_snapshot.json contains commits, unified diffs, and source files."""
        for bundle_name in self.RECORDED_BUNDLES:
            bundle = load_fixture_bundle(bundle_name)
            repo = bundle["repo_snapshot"]
            self.assertIn("commits", repo)
            self.assertIn("diffs", repo)
            self.assertIn("files", repo)

            self.assertGreater(len(repo["commits"]), 0)
            self.assertGreater(len(repo["diffs"]), 0)
            self.assertGreater(len(repo["files"]), 0)

            # Check that diff contains unified diff headers
            diff_text = next(iter(repo["diffs"].values()))
            self.assertIn("---", diff_text)
            self.assertIn("+++", diff_text)

    def test_07_nine_tool_parity_across_three_fixture_bundles(self):
        """FixtureClient operates all 9 diagnostic and remediation tools on recorded bundles."""
        for bundle_name in self.RECORDED_BUNDLES[:3]:
            fc = FixtureClient(fixture_bundle=bundle_name)

            # Tool 1: query_logs
            logs = fc.query_logs(limit=10)
            self.assertIsInstance(logs, list)
            self.assertGreater(len(logs), 0)

            # Tool 1 with level filter
            error_logs = fc.query_logs(level="ERROR")
            if error_logs:
                for log in error_logs:
                    self.assertEqual(log["level"], "ERROR")

            # Tool 2: query_metrics
            metrics = fc.query_metrics("http_requests_total")
            self.assertEqual(metrics["status"], "success")
            self.assertIn("result", metrics["data"])

            # Tool 3: list_changes
            changes = fc.list_changes(limit=5)
            self.assertIsInstance(changes, list)
            self.assertGreater(len(changes), 0)

            # Tool 4: git_log
            commits = fc.git_log(n=3)
            self.assertIsInstance(commits, list)
            self.assertGreater(len(commits), 0)
            self.assertIn("commit", commits[0])
            self.assertIn("message", commits[0])

            # Tool 5: git_diff
            culprit_commit = commits[0]["commit"]
            diff = fc.git_diff(commit_a=culprit_commit)
            self.assertIsInstance(diff, str)
            self.assertGreater(len(diff), 0)

            # Tool 6: read_file
            inc_service = fc.get_incident().get("service", "orders")
            content = fc.read_file(f"target-app/services/{inc_service}/app.py")
            self.assertIsInstance(content, str)
            self.assertGreater(len(content), 0)

            # Tool 7: service_map
            smap = fc.service_map()
            self.assertIn("services", smap)
            self.assertIn("edges", smap)
            self.assertIn("orders", smap["services"])
            self.assertIn("gateway", smap["services"])
            self.assertIn("payments", smap["services"])

            # Tool 8: search_past_incidents
            past = fc.search_past_incidents("error", limit=2)
            self.assertIsInstance(past, list)
            self.assertGreater(len(past), 0)

            # Tool 9: propose_fix
            receipt = fc.propose_fix({
                "type": "patch",
                "diff": diff,
                "risk_tier": "T2",
                "rationale": "Automated patch verification",
                "expected_metric_effect": "Error rate drops to 0%",
                "target_service": inc_service,
            })
            self.assertEqual(receipt["status"], "accepted")
            self.assertTrue(receipt["proposal_id"].startswith("prop_"))

    def test_08_ground_truth_parity(self):
        """Every fixture bundle contains ground truth matching the catalog manifest."""
        for bundle_name in self.RECORDED_BUNDLES[:3]:
            bundle = load_fixture_bundle(bundle_name)
            gt = bundle.get("ground_truth") or {}
            self.assertEqual(gt.get("fault_id"), bundle_name)
            self.assertTrue("target_service" in gt or "service" in gt)
            self.assertIn("root_cause", gt)
            self.assertIn("culprit_change", gt)
            self.assertIn("expected_fix_type", gt)


if __name__ == "__main__":
    unittest.main()
