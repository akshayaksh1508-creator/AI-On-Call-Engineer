"""Unit and table-driven policy tests for SafetyGate.

Owner: Person B
Architecture Section 6 & Day 5 Task B1:
- Tiers T0 to T3
- Confidence thresholds (T1 >= 0.80, T2 >= 0.85 in demo)
- One action per incident per 10 minutes (600s cooldown)
- Global kill switch
- Path and service allowlist
- 15 table-driven policy tests; a T3 action is never executed automatically
"""

import os
import tempfile
import unittest
from pathlib import Path

from contracts.models import FixProposal
from safety.gate import (
    ActionRequest,
    GateDecision,
    PolicyEvaluation,
    RiskTier,
    SafetyGate,
)


class TestTableDrivenPolicy(unittest.TestCase):
    """15 table-driven policy tests validating SafetyGate behavior against Section 6."""

    def setUp(self):
        self.gate = SafetyGate(demo_mode=True)

    def test_fifteen_table_driven_policy_matrix(self):
        """Execute 15+ distinct table-driven test cases covering tiers, thresholds, allowlists, limits, and kill switch."""
        test_cases = [
            # 1. T0 Read operation (logs/metrics/code) -> AUTOMATIC
            {
                "name": "case_01_t0_read_logs_high_confidence",
                "request": ActionRequest(
                    incident_id="inc-01",
                    action_type="read",
                    confidence=1.0,
                    target_service="orders",
                ),
                "expected_decision": GateDecision.AUTOMATIC,
                "expected_tier": RiskTier.T0,
                "expected_allowed": True,
            },
            # 2. T0 Read operation with low confidence -> still AUTOMATIC (reads are always automatic)
            {
                "name": "case_02_t0_read_metrics_low_confidence",
                "request": ActionRequest(
                    incident_id="inc-02",
                    action_type="query",
                    confidence=0.25,
                    target_service="gateway",
                ),
                "expected_decision": GateDecision.AUTOMATIC,
                "expected_tier": RiskTier.T0,
                "expected_allowed": True,
            },
            # 3. T1 Rollback with confidence >= 0.80 -> AUTOMATIC
            {
                "name": "case_03_t1_rollback_above_threshold",
                "request": ActionRequest(
                    incident_id="inc-03",
                    action_type="rollback",
                    confidence=0.88,
                    target_service="orders",
                ),
                "expected_decision": GateDecision.AUTOMATIC,
                "expected_tier": RiskTier.T1,
                "expected_allowed": True,
            },
            # 4. T1 Rollback at exact boundary 0.80 -> AUTOMATIC
            {
                "name": "case_04_t1_rollback_exact_boundary",
                "request": ActionRequest(
                    incident_id="inc-04",
                    action_type="rollback",
                    confidence=0.80,
                    target_service="orders",
                ),
                "expected_decision": GateDecision.AUTOMATIC,
                "expected_tier": RiskTier.T1,
                "expected_allowed": True,
            },
            # 5. T1 Rollback sub-threshold (0.79 < 0.80) -> HUMAN_APPROVAL_REQUIRED
            {
                "name": "case_05_t1_rollback_below_threshold",
                "request": ActionRequest(
                    incident_id="inc-05",
                    action_type="rollback",
                    confidence=0.79,
                    target_service="orders",
                ),
                "expected_decision": GateDecision.HUMAN_APPROVAL_REQUIRED,
                "expected_tier": RiskTier.T1,
                "expected_allowed": False,
            },
            # 6. T1 Config revert with low confidence (0.60 < 0.80) -> HUMAN_APPROVAL_REQUIRED
            {
                "name": "case_06_t1_config_revert_low_confidence",
                "request": ActionRequest(
                    incident_id="inc-06",
                    action_type="config",
                    confidence=0.60,
                    target_service="payments",
                ),
                "expected_decision": GateDecision.HUMAN_APPROVAL_REQUIRED,
                "expected_tier": RiskTier.T1,
                "expected_allowed": False,
            },
            # 7. T2 Code patch in demo mode with confidence >= 0.85 -> AUTOMATIC
            {
                "name": "case_07_t2_code_patch_demo_above_threshold",
                "request": ActionRequest(
                    incident_id="inc-07",
                    action_type="patch",
                    confidence=0.92,
                    target_service="orders",
                    environment="demo",
                    affected_paths=["services/orders/app.py"],
                ),
                "expected_decision": GateDecision.AUTOMATIC,
                "expected_tier": RiskTier.T2,
                "expected_allowed": True,
            },
            # 8. T2 Code patch in demo mode at exact boundary 0.85 -> AUTOMATIC
            {
                "name": "case_08_t2_code_patch_demo_exact_boundary",
                "request": ActionRequest(
                    incident_id="inc-08",
                    action_type="patch",
                    confidence=0.85,
                    target_service="orders",
                    environment="demo",
                    affected_paths=["services/orders/app.py"],
                ),
                "expected_decision": GateDecision.AUTOMATIC,
                "expected_tier": RiskTier.T2,
                "expected_allowed": True,
            },
            # 9. T2 Code patch in demo mode sub-threshold (0.84 < 0.85) -> HUMAN_APPROVAL_REQUIRED
            {
                "name": "case_09_t2_code_patch_demo_below_threshold",
                "request": ActionRequest(
                    incident_id="inc-09",
                    action_type="patch",
                    confidence=0.84,
                    target_service="orders",
                    environment="demo",
                    affected_paths=["services/orders/app.py"],
                ),
                "expected_decision": GateDecision.HUMAN_APPROVAL_REQUIRED,
                "expected_tier": RiskTier.T2,
                "expected_allowed": False,
            },
            # 10. T2 Code patch in production mode (non-demo) -> HUMAN_APPROVAL_REQUIRED (even if conf 0.99)
            {
                "name": "case_10_t2_code_patch_production_mode",
                "request": ActionRequest(
                    incident_id="inc-10",
                    action_type="patch",
                    confidence=0.99,
                    target_service="orders",
                    environment="production",
                    affected_paths=["services/orders/app.py"],
                ),
                "expected_decision": GateDecision.HUMAN_APPROVAL_REQUIRED,
                "expected_tier": RiskTier.T2,
                "expected_allowed": False,
            },
            # 11. T3 Database migration action -> HUMAN_APPROVAL_REQUIRED (never automatic)
            {
                "name": "case_11_t3_database_migration_action",
                "request": ActionRequest(
                    incident_id="inc-11",
                    action_type="migration",
                    confidence=1.0,
                    target_service="orders_db",
                    affected_paths=["migrations/001_add_column.sql"],
                ),
                "expected_decision": GateDecision.HUMAN_APPROVAL_REQUIRED,
                "expected_tier": RiskTier.T3,
                "expected_allowed": False,
            },
            # 12. T3 Patch touching SQL/migration file -> inferred T3 -> HUMAN_APPROVAL_REQUIRED
            {
                "name": "case_12_t3_patch_touching_migration_file",
                "request": ActionRequest(
                    incident_id="inc-12",
                    action_type="patch",
                    confidence=0.95,
                    target_service="orders",
                    diff="diff --git a/migrations/schema.sql b/migrations/schema.sql\n--- a/migrations/schema.sql\n+++ b/migrations/schema.sql",
                ),
                "expected_decision": GateDecision.HUMAN_APPROVAL_REQUIRED,
                "expected_tier": RiskTier.T3,
                "expected_allowed": False,
            },
            # 13. T3 Infrastructure / docker deletion -> HUMAN_APPROVAL_REQUIRED
            {
                "name": "case_13_t3_infrastructure_modification",
                "request": ActionRequest(
                    incident_id="inc-13",
                    action_type="infra",
                    confidence=1.0,
                    target_service="orders",
                    affected_paths=["docker-compose.yml"],
                ),
                "expected_decision": GateDecision.HUMAN_APPROVAL_REQUIRED,
                "expected_tier": RiskTier.T3,
                "expected_allowed": False,
            },
            # 14. Disallowed Service -> REJECTED
            {
                "name": "case_14_service_allowlist_violation",
                "request": ActionRequest(
                    incident_id="inc-14",
                    action_type="rollback",
                    confidence=0.90,
                    target_service="unapproved_external_service",
                ),
                "expected_decision": GateDecision.REJECTED,
                "expected_tier": RiskTier.T1,
                "expected_allowed": False,
            },
            # 15. Disallowed Path Traversal -> REJECTED
            {
                "name": "case_15_path_traversal_violation",
                "request": ActionRequest(
                    incident_id="inc-15",
                    action_type="patch",
                    confidence=0.95,
                    target_service="orders",
                    affected_paths=["services/../../etc/shadow"],
                ),
                "expected_decision": GateDecision.REJECTED,
                "expected_tier": RiskTier.T2,
                "expected_allowed": False,
            },
            # 16. Forbidden Secret File (.env) -> REJECTED
            {
                "name": "case_16_forbidden_secret_path",
                "request": ActionRequest(
                    incident_id="inc-16",
                    action_type="patch",
                    confidence=0.95,
                    target_service="orders",
                    affected_paths=[".env.production"],
                ),
                "expected_decision": GateDecision.REJECTED,
                "expected_tier": RiskTier.T2,
                "expected_allowed": False,
            },
        ]

        self.assertGreaterEqual(len(test_cases), 15, "Must test at least 15 table-driven cases")

        for case in test_cases:
            with self.subTest(case=case["name"]):
                eval_res = self.gate.evaluate(case["request"])
                self.assertEqual(
                    eval_res.decision,
                    case["expected_decision"],
                    f"[{case['name']}] Decision mismatch: got {eval_res.decision}, expected {case['expected_decision']}. Reason: {eval_res.reason}",
                )
                self.assertEqual(
                    eval_res.risk_tier,
                    case["expected_tier"],
                    f"[{case['name']}] Risk tier mismatch: got {eval_res.risk_tier}, expected {case['expected_tier']}",
                )
                self.assertEqual(
                    eval_res.allowed,
                    case["expected_allowed"],
                    f"[{case['name']}] Allowed mismatch: got {eval_res.allowed}, expected {case['expected_allowed']}",
                )


class TestT3NeverAutomatic(unittest.TestCase):
    """Exit gate validation: A T3 action is NEVER executed automatically under any condition."""

    def setUp(self):
        self.gate = SafetyGate(demo_mode=True)

    def test_t3_is_never_executed_automatically_across_all_confidences_and_environments(self):
        """Verify that across 0.0 to 1.0 confidence and various environments, T3 never yields AUTOMATIC."""
        confidences = [0.0, 0.1, 0.5, 0.79, 0.80, 0.85, 0.90, 0.95, 0.99, 1.0]
        environments = ["demo", "production", "staging", "test"]
        t3_action_types = ["migration", "data", "infra", "delete_infra", "secrets"]

        total_tested = 0
        for conf in confidences:
            for env in environments:
                for action in t3_action_types:
                    req = ActionRequest(
                        incident_id=f"inc-t3-{conf}-{env}-{action}",
                        action_type=action,
                        confidence=conf,
                        environment=env,
                        target_service="orders",
                    )
                    res = self.gate.evaluate(req)

                    self.assertEqual(res.risk_tier, RiskTier.T3)
                    self.assertFalse(res.allowed, f"T3 action {action} must NOT be allowed automatically at conf {conf}")
                    self.assertNotEqual(
                        res.decision,
                        GateDecision.AUTOMATIC,
                        f"T3 action {action} yielded AUTOMATIC decision at confidence {conf} in {env}",
                    )
                    self.assertTrue(res.requires_approval or res.decision == GateDecision.REJECTED)
                    total_tested += 1

        self.assertGreater(total_tested, 50, "Tested over 50 combinations of T3 actions")


class TestRateLimitingTenMinuteCooldown(unittest.TestCase):
    """Validation: One action per incident per 10 minutes (600s cooldown)."""

    def setUp(self):
        self.gate = SafetyGate(cooldown_seconds=600.0, demo_mode=True)

    def test_one_action_per_incident_per_ten_minutes(self):
        """Verify second mutating action on the same incident within 600s is rejected."""
        inc_id = "inc-rate-test-1"
        t0 = 100000.0

        req1 = ActionRequest(
            incident_id=inc_id,
            action_type="rollback",
            confidence=0.90,
            target_service="orders",
        )

        # First action is allowed
        res1 = self.gate.evaluate(req1, now=t0)
        self.assertEqual(res1.decision, GateDecision.AUTOMATIC)
        self.assertTrue(res1.allowed)

        # Record action execution
        self.gate.record_action(inc_id, timestamp=t0)

        # Immediate follow-up attempt (t0 + 5s) -> REJECTED
        res2 = self.gate.evaluate(req1, now=t0 + 5.0)
        self.assertEqual(res2.decision, GateDecision.REJECTED)
        self.assertFalse(res2.allowed)
        self.assertIn("RATE_LIMIT_COOLDOWN_ACTIVE", res2.violations)

        # Follow-up at 300s (5 minutes in) -> REJECTED
        res3 = self.gate.evaluate(req1, now=t0 + 300.0)
        self.assertEqual(res3.decision, GateDecision.REJECTED)
        self.assertFalse(res3.allowed)

        # Follow-up at 599s (9m 59s in) -> REJECTED
        res4 = self.gate.evaluate(req1, now=t0 + 599.0)
        self.assertEqual(res4.decision, GateDecision.REJECTED)
        self.assertFalse(res4.allowed)

        # Follow-up at 601s (10m 1s in) -> AUTOMATIC (cooldown expired)
        res5 = self.gate.evaluate(req1, now=t0 + 601.0)
        self.assertEqual(res5.decision, GateDecision.AUTOMATIC)
        self.assertTrue(res5.allowed)

    def test_rate_limiting_is_isolated_per_incident(self):
        """Action on incident A does not block incident B."""
        t0 = 200000.0
        self.gate.record_action("inc-A", timestamp=t0)

        req_b = ActionRequest(
            incident_id="inc-B",
            action_type="rollback",
            confidence=0.90,
            target_service="orders",
        )

        # Incident B should be allowed immediately
        res_b = self.gate.evaluate(req_b, now=t0 + 10.0)
        self.assertEqual(res_b.decision, GateDecision.AUTOMATIC)
        self.assertTrue(res_b.allowed)


class TestKillSwitch(unittest.TestCase):
    """Validation: Global kill switch halts all remediation actions."""

    def test_programmatic_trip_and_reset(self):
        gate = SafetyGate(demo_mode=True)
        req = ActionRequest(
            incident_id="inc-kill-1",
            action_type="rollback",
            confidence=0.95,
            target_service="orders",
        )

        # Normal condition -> approved
        res = gate.evaluate(req)
        self.assertEqual(res.decision, GateDecision.AUTOMATIC)

        # Trip kill switch
        gate.trip_kill_switch("Emergency operator freeze")
        self.assertTrue(gate.is_kill_switch_active())

        # Now evaluation must be REJECTED
        res_tripped = gate.evaluate(req)
        self.assertEqual(res_tripped.decision, GateDecision.REJECTED)
        self.assertFalse(res_tripped.allowed)
        self.assertIn("Emergency operator freeze", res_tripped.reason)

        # Reset kill switch
        gate.reset_kill_switch()
        self.assertFalse(gate.is_kill_switch_active())
        res_restored = gate.evaluate(req)
        self.assertEqual(res_restored.decision, GateDecision.AUTOMATIC)

    def test_environment_variable_kill_switch(self):
        gate = SafetyGate(demo_mode=True)
        req = ActionRequest(
            incident_id="inc-kill-2",
            action_type="rollback",
            confidence=0.95,
            target_service="orders",
        )

        old_val = os.environ.get("NIGHTSHIFT_KILL_SWITCH")
        try:
            os.environ["NIGHTSHIFT_KILL_SWITCH"] = "true"
            self.assertTrue(gate.is_kill_switch_active())
            res = gate.evaluate(req)
            self.assertEqual(res.decision, GateDecision.REJECTED)
            self.assertFalse(res.allowed)
        finally:
            if old_val is not None:
                os.environ["NIGHTSHIFT_KILL_SWITCH"] = old_val
            else:
                os.environ.pop("NIGHTSHIFT_KILL_SWITCH", None)

    def test_file_flag_kill_switch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            flag_file = Path(tmpdir) / "nightshift.kill"
            gate = SafetyGate(kill_switch_path=flag_file, demo_mode=True)
            req = ActionRequest(
                incident_id="inc-kill-3",
                action_type="rollback",
                confidence=0.95,
                target_service="orders",
            )

            self.assertFalse(gate.is_kill_switch_active())
            self.assertEqual(gate.evaluate(req).decision, GateDecision.AUTOMATIC)

            # Create kill switch file
            flag_file.write_text("operator tripped kill switch")
            self.assertTrue(gate.is_kill_switch_active())
            self.assertEqual(gate.evaluate(req).decision, GateDecision.REJECTED)

            # Delete file
            flag_file.unlink()
            self.assertFalse(gate.is_kill_switch_active())
            self.assertEqual(gate.evaluate(req).decision, GateDecision.AUTOMATIC)


class TestFixProposalIntegration(unittest.TestCase):
    """Validation: Integration between FixProposal contract and SafetyGate."""

    def setUp(self):
        self.gate = SafetyGate(demo_mode=True)

    def test_evaluate_fix_proposal_patch(self):
        proposal = FixProposal(
            type="patch",
            diff="diff --git a/services/orders/app.py b/services/orders/app.py\n--- a/services/orders/app.py\n+++ b/services/orders/app.py\n@@ -1 +1 @@",
            risk_tier="T2",
            rationale="Fix null pointer exception in VIP user handling",
            expected_metric_effect="Error rate drops to 0%",
            target_service="orders",
        )

        # High confidence -> AUTOMATIC in demo
        res_high = self.gate.evaluate_proposal(proposal, confidence=0.90)
        self.assertEqual(res_high.decision, GateDecision.AUTOMATIC)
        self.assertEqual(res_high.risk_tier, RiskTier.T2)
        self.assertTrue(res_high.allowed)

        # Low confidence -> HUMAN_APPROVAL_REQUIRED
        res_low = self.gate.evaluate_proposal(proposal, confidence=0.70)
        self.assertEqual(res_low.decision, GateDecision.HUMAN_APPROVAL_REQUIRED)
        self.assertEqual(res_low.risk_tier, RiskTier.T2)
        self.assertFalse(res_low.allowed)

    def test_evaluate_fix_proposal_rollback(self):
        proposal = FixProposal(
            type="rollback",
            diff="",
            risk_tier="T1",
            rationale="Roll back to previous stable release",
            expected_metric_effect="Restores 200 responses",
            target_service="orders",
        )

        res = self.gate.evaluate_proposal(proposal, confidence=0.82)
        self.assertEqual(res.decision, GateDecision.AUTOMATIC)
        self.assertEqual(res.risk_tier, RiskTier.T1)
        self.assertTrue(res.allowed)


if __name__ == "__main__":
    unittest.main()
