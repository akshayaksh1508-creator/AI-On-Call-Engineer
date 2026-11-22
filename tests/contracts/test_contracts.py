"""Contract and Tool Parity Tests for Task A4.

Verifies:
1. Pydantic contract schemas and exported JSON schemas.
2. Fixture bundle loading and schema validation.
3. 9-tool interface parity across both FixtureClient and StubPlatformAPI (StubClient).
4. Person B import paths.
"""

import unittest
from pathlib import Path

# Person B Import Verification
from contracts import (
    Incident,
    Evidence,
    Hypothesis,
    FixProposal,
    VerificationResult,
    RunRecord,
    get_schema,
    load_fixture_bundle,
)
from platform_api import (
    PlatformClient,
    FixtureClient,
    StubClient,
    create_platform_client,
)


class TestContractsAndSchemas(unittest.TestCase):
    """Test suite validating schemas and Pydantic models."""

    def test_01_incident_model_validation(self):
        """Incident model validates required fields and default status."""
        inc = Incident(
            id="inc_test_001",
            service="orders",
            started_at="2026-11-22T21:40:00Z",
            symptoms=["500 error spike"],
            alerts=["OrdersHigh5xxRate"],
            recent_changes=["dep_001"],
        )
        self.assertEqual(inc.id, "inc_test_001")
        self.assertEqual(inc.status, "open")
        self.assertEqual(inc.service, "orders")

    def test_02_hypothesis_confidence_bounds(self):
        """Hypothesis confidence must be between 0.0 and 1.0."""
        hyp = Hypothesis(
            cause="Null pointer in discount calculation",
            category="code",
            confidence=0.92,
            evidence_ids=["ev_1", "ev_2"],
            culprit_change="c0ffee1",
        )
        self.assertEqual(hyp.confidence, 0.92)

        # Out of bounds confidence should raise ValueError
        with self.assertRaises(ValueError):
            Hypothesis(
                cause="Bad deploy",
                category="code",
                confidence=1.5,
            )

    def test_03_fix_proposal_validation(self):
        """FixProposal accepts valid risk tiers and remediation types."""
        fix = FixProposal(
            type="patch",
            diff="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@",
            risk_tier="T2",
            rationale="Defensive null check on discount payload",
            expected_metric_effect="Error rate drops to 0%",
            target_service="orders",
        )
        self.assertEqual(fix.risk_tier, "T2")
        self.assertEqual(fix.type, "patch")

    def test_04_verification_result_and_run_record(self):
        """VerificationResult and RunRecord model serialization."""
        vr = VerificationResult(
            tests_passed=True,
            repro_fixed=True,
            canary_healthy=True,
            metric_before=0.35,
            metric_after=0.005,
            recovered_at="2026-11-22T21:45:00Z",
            verdict="PASS",
        )
        self.assertEqual(vr.verdict, "PASS")

        rr = RunRecord(
            incident_id="inc_001",
            fault_id="fault_001_bad_deploy",
            t_detect=12.5,
            t_rca=45.0,
            t_fix=30.0,
            t_verified=60.0,
            rca_correct_top1=True,
            rca_correct_top3=True,
            fix_ok=True,
            tokens=4500,
            cost_usd=0.03,
        )
        self.assertTrue(rr.rca_correct_top1)
        self.assertEqual(rr.fault_id, "fault_001_bad_deploy")

    def test_05_exported_json_schemas_exist_and_match(self):
        """JSON Schema export files exist and define the expected JSON schema."""
        for model_name in ["Incident", "Evidence", "Hypothesis", "FixProposal", "VerificationResult", "RunRecord"]:
            schema = get_schema(model_name)
            self.assertIn("properties", schema)
            self.assertEqual(schema.get("title"), model_name)


class TestRecordedFixtureBundle(unittest.TestCase):
    """Test suite validating the recorded incident fixture bundle."""

    def test_06_fixture_bundle_loading(self):
        """Fixture bundle 'fault_001_bad_deploy' loads completely with valid incident."""
        bundle = load_fixture_bundle("fault_001_bad_deploy")
        self.assertIn("incident", bundle)
        self.assertIn("logs", bundle)
        self.assertIn("metrics", bundle)
        self.assertIn("changes", bundle)
        self.assertIn("service_map", bundle)

        # Validate that incident parses into Incident model
        inc = Incident(**bundle["incident"])
        self.assertEqual(inc.id, "inc_20261122_001")
        self.assertEqual(inc.service, "orders")

    def test_07_fixture_logs_contain_error_trace(self):
        """Fixture logs contain the expected TypeError exception and trace ID."""
        bundle = load_fixture_bundle("fault_001_bad_deploy")
        logs = bundle["logs"]
        error_logs = [log for log in logs if log.get("level") == "ERROR"]
        self.assertGreater(len(error_logs), 0)

        found_type_error = any("TypeError" in log.get("message", "") for log in error_logs)
        self.assertTrue(found_type_error, "Logs must contain TypeError for fault_001_bad_deploy")


class TestPlatformClientParity(unittest.TestCase):
    """Test suite verifying all 9 tools across FixtureClient and StubClient."""

    def setUp(self):
        self.fixture_client: PlatformClient = create_platform_client(mode="fixture")
        self.stub_client: PlatformClient = create_platform_client(mode="stub")

    def test_08_tool_1_query_logs_parity(self):
        """Tool 1: query_logs filters by service and level."""
        for client in [self.fixture_client, self.stub_client]:
            logs = client.query_logs(service="orders", level="ERROR")
            self.assertIsInstance(logs, list)
            self.assertGreater(len(logs), 0)
            for log in logs:
                self.assertEqual(log["service"], "orders")
                self.assertEqual(log["level"], "ERROR")

    def test_09_tool_2_query_metrics_parity(self):
        """Tool 2: query_metrics returns time series matrix."""
        for client in [self.fixture_client, self.stub_client]:
            metrics = client.query_metrics("http_requests_total")
            self.assertIn("status", metrics)
            self.assertEqual(metrics["status"], "success")
            self.assertIn("data", metrics)
            self.assertIn("result", metrics["data"])

    def test_10_tool_3_list_changes_parity(self):
        """Tool 3: list_changes returns deploy history."""
        for client in [self.fixture_client, self.stub_client]:
            changes = client.list_changes(service="orders")
            self.assertIsInstance(changes, list)
            self.assertGreater(len(changes), 0)
            self.assertEqual(changes[0]["service"], "orders")
            self.assertEqual(changes[0]["version"], "v1.0.1")

    def test_11_tool_4_git_log_parity(self):
        """Tool 4: git_log returns commit list with message."""
        for client in [self.fixture_client, self.stub_client]:
            commits = client.git_log(n=5)
            self.assertIsInstance(commits, list)
            self.assertGreater(len(commits), 0)
            self.assertIn("commit", commits[0])
            self.assertIn("message", commits[0])

    def test_12_tool_5_git_diff_parity(self):
        """Tool 5: git_diff returns unified diff."""
        for client in [self.fixture_client, self.stub_client]:
            diff = client.git_diff(commit_a="c0ffee14a")
            self.assertIsInstance(diff, str)
            self.assertIn("diff --git", diff)
            self.assertIn("discount", diff)

    def test_13_tool_6_read_file_parity(self):
        """Tool 6: read_file returns content and supports line ranges."""
        for client in [self.fixture_client, self.stub_client]:
            content = client.read_file("target-app/services/orders/main.py")
            self.assertIsInstance(content, str)
            self.assertIn("FastAPI", content)

            # Test line slicing (lines 1 to 3)
            slice_content = client.read_file(
                "target-app/services/orders/main.py", start_line=1, end_line=3
            )
            self.assertEqual(len(slice_content.splitlines()), 3)

    def test_14_tool_7_service_map_parity(self):
        """Tool 7: service_map returns microservice topology nodes and edges."""
        for client in [self.fixture_client, self.stub_client]:
            smap = client.service_map()
            self.assertIn("services", smap)
            self.assertIn("edges", smap)
            self.assertIn("orders", smap["services"])
            self.assertIn("gateway", smap["services"])

    def test_15_tool_8_search_past_incidents_parity(self):
        """Tool 8: search_past_incidents finds past incident by keyword."""
        for client in [self.fixture_client, self.stub_client]:
            results = client.search_past_incidents(query="null pointer discount", limit=2)
            self.assertIsInstance(results, list)
            self.assertGreater(len(results), 0)
            self.assertIn("inc_20261015_004", results[0]["id"])

    def test_16_tool_9_propose_fix_parity(self):
        """Tool 9: propose_fix validates FixProposal and returns receipt."""
        proposal = FixProposal(
            type="patch",
            diff="--- a/target-app/services/orders/main.py\n+++ b/target-app/services/orders/main.py\n@@ -42 +42 @@\n- discount_code = discount['code']\n+ discount_code = discount.get('code') if discount else None",
            risk_tier="T2",
            rationale="Add defensive check for discount payload",
            expected_metric_effect="500 error rate drops from 35% to 0%",
            target_service="orders",
        )

        for client in [self.fixture_client, self.stub_client]:
            receipt = client.propose_fix(proposal)
            self.assertIsInstance(receipt, dict)
            self.assertEqual(receipt["status"], "accepted")
            self.assertEqual(receipt["risk_tier"], "T2")
            self.assertTrue(receipt["proposal_id"].startswith("prop_"))


if __name__ == "__main__":
    unittest.main()
