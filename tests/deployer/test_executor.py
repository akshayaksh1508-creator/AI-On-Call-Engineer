"""Unit tests for Action Executor (Day 6 Task A2).

Verifies:
1. T1 rollback executes directly via Deployer (bypassing sandbox and canary).
2. T2 code patch executes through all 3 stages in strict order: Sandbox -> Canary -> Promote.
3. Strict early abort: Stage 1 (Sandbox) failure halts before Canary or Promote.
4. Strict early abort: Stage 2 (Canary) failure halts before Promote.
5. Post-promotion metric degradation triggers Auto-Rollback in Stage 3.
6. Works with both FixProposal (contracts.models) and ActionRequest (safety.gate).
7. End-to-end integration with real ReleaseManager and ChangeLog.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Ensure repo root is on path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.models import FixProposal, VerificationResult
from deployer.changes import ChangeLog
from deployer.executor import ActionExecutor, ExecutionResult
from deployer.release_manager import ReleaseManager
from deployer.runners import NoopRunner
from safety.gate import ActionRequest, RiskTier
from verifier.canary import CanaryResult
from verifier.sandbox import SandboxRun


def make_test_git_repo(root: Path):
    """Create a temporary git repository with 2 commits for deployer testing."""
    repo = root / "app"
    repo.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@nightshift.local",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@nightshift.local",
    }

    def _sh(*args):
        return subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=env
        ).stdout.strip()

    _sh("init", "-q")
    shas = []
    for i in (1, 2):
        (repo / "version.txt").write_text(f"v{i}", encoding="utf-8")
        _sh("add", ".")
        _sh("commit", "-qm", f"release v{i}")
        shas.append(_sh("rev-parse", "HEAD"))
    return repo, shas


class TestActionExecutor(unittest.TestCase):
    """Test suite for Day 6 Task A2 ActionExecutor."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo, self.shas = make_test_git_repo(self.root)
        self.changelog = ChangeLog(self.root / "data" / "changes.jsonl")
        self.runner = NoopRunner()
        self.release_manager = ReleaseManager(
            self.repo,
            self.root / "data" / "state.json",
            self.changelog,
            self.runner,
            releases_dir=self.root / "rel",
        )
        # Bootstrap service at v1, then deploy v2
        self.release_manager.bootstrap("orders", self.shas[0])
        self.release_manager.deploy("orders", self.shas[1], author="ci", message="deploy v2")

    def tearDown(self):
        self.tmp.cleanup()

    def test_01_t1_rollback_executes_directly(self):
        """Exit criterion: A T1 rollback executes directly bypassing sandbox and canary."""
        mock_sandbox = MagicMock()
        mock_canary = MagicMock()

        executor = ActionExecutor(
            repo_root=self.repo,
            release_manager=self.release_manager,
            sandbox_verifier=mock_sandbox,
            canary_verifier=mock_canary,
        )

        proposal = FixProposal(
            type="rollback",
            risk_tier="T1",
            diff="",
            rationale="Revert broken deployment v2",
            expected_metric_effect="Error rate drops to 0%",
            target_service="orders",
        )

        res = executor.execute(proposal, incident_id="inc_t1_001")

        self.assertTrue(res.success)
        self.assertEqual(res.action_type, "rollback")
        self.assertEqual(res.risk_tier, "T1")
        self.assertEqual(res.service, "orders")
        self.assertEqual(res.stages_executed, ["direct_rollback"])
        self.assertFalse(res.aborted)
        self.assertIsNone(res.failed_stage)

        # Sandbox and Canary must NEVER be invoked for a T1 rollback
        mock_sandbox.verify.assert_not_called()
        mock_canary.evaluate.assert_not_called()

        # Check ReleaseManager rolled back to v1
        self.assertEqual(self.release_manager.current("orders"), self.shas[0])
        events = self.changelog.list(service="orders")
        self.assertEqual(events[-1]["type"], "rollback")
        self.assertEqual(events[-1]["to_ref"], self.shas[0])

    def test_02_t2_patch_passes_all_three_stages_in_order(self):
        """Exit criterion: A T2 patch passes sandbox -> canary -> promote in strict order."""
        call_order = []

        mock_sandbox = MagicMock()

        def _sandbox_verify(*args, **kwargs):
            call_order.append("sandbox")
            dummy_vr = VerificationResult(
                tests_passed=True,
                repro_fixed=True,
                canary_healthy=False,
                metric_before=0.20,
                metric_after=0.20,
                recovered_at=None,
                verdict="FAIL",
            )
            return SandboxRun(
                verification=dummy_vr,
                accepted=True,
                error=None,
                reproduction_failed_before=True,
                unit_test_output="OK",
                reproduction_output="PASS",
            )

        mock_sandbox.verify.side_effect = _sandbox_verify

        mock_canary = MagicMock()

        def _canary_eval(*args, **kwargs):
            call_order.append("canary")
            return MagicMock(healthy=True, verdict="PASS", reason="latency and error rate nominal")

        mock_canary.evaluate.side_effect = _canary_eval

        def mock_deploy(service, ref, author, message):
            call_order.append("promote")
            return {"service": service, "ref": ref, "deployed": True}

        executor = ActionExecutor(
            repo_root=self.repo,
            release_manager=self.release_manager,
            sandbox_verifier=mock_sandbox,
            canary_verifier=mock_canary,
            deploy_fn=mock_deploy,
        )

        proposal = FixProposal(
            type="patch",
            risk_tier="T2",
            diff="--- a/target-app/services/orders/app.py\n+++ b/target-app/services/orders/app.py\n@@ -1,1 +1,1 @@\n-broken\n+fixed\n",
            rationale="Fix index boundary bug",
            expected_metric_effect="5xx drop below 1%",
            target_service="orders",
        )

        res = executor.execute(
            proposal,
            incident_id="inc_t2_001",
            fault_id="fault_002_off_by_one",
            post_promotion_error_rate=0.001,
        )

        self.assertTrue(res.success)
        self.assertFalse(res.aborted)
        self.assertIsNone(res.failed_stage)
        self.assertEqual(res.stages_executed, ["sandbox", "canary", "promote"])
        self.assertEqual(call_order, ["sandbox", "canary", "promote"], "Stages must execute strictly in order")
        self.assertIsNotNone(res.verification)
        self.assertEqual(res.verification.verdict, "PASS")
        self.assertEqual(res.verification.metric_after, 0.001)

    def test_03_sandbox_failure_aborts_before_canary_or_promote(self):
        """Exit criterion: Stage 1 (Sandbox) failure halts immediately before canary or promote."""
        mock_sandbox = MagicMock()
        mock_sandbox.verify.return_value = SandboxRun(
            verification=VerificationResult(
                tests_passed=False,  # Tests failed in sandbox!
                repro_fixed=False,
                canary_healthy=False,
                metric_before=0.20,
                metric_after=0.20,
                verdict="FAIL",
            ),
            accepted=False,
            error="Unit test failed: AssertionError on orders total",
            reproduction_failed_before=True,
            unit_test_output="FAIL",
            reproduction_output="FAIL",
        )

        mock_canary = MagicMock()
        mock_deploy = MagicMock()

        executor = ActionExecutor(
            repo_root=self.repo,
            sandbox_verifier=mock_sandbox,
            canary_verifier=mock_canary,
            deploy_fn=mock_deploy,
        )

        proposal = FixProposal(
            type="patch",
            risk_tier="T2",
            diff="diff --git a/app.py b/app.py",
            rationale="Fix bug",
            expected_metric_effect="recover",
            target_service="orders",
        )

        res = executor.execute(proposal, incident_id="inc_sb_fail_001")

        self.assertFalse(res.success)
        self.assertTrue(res.aborted)
        self.assertEqual(res.failed_stage, "sandbox")
        self.assertEqual(res.stages_executed, ["sandbox"])
        self.assertIn("Sandbox", res.message)

        # STRICT ABORT: Canary and Promote must NEVER be called
        mock_canary.evaluate.assert_not_called()
        mock_deploy.assert_not_called()

    def test_04_canary_failure_aborts_before_promote(self):
        """Exit criterion: Stage 2 (Canary) failure halts immediately before promote."""
        mock_sandbox = MagicMock()
        mock_sandbox.verify.return_value = SandboxRun(
            verification=VerificationResult(
                tests_passed=True,
                repro_fixed=True,
                canary_healthy=False,
                metric_before=0.20,
                metric_after=0.20,
                verdict="FAIL",
            ),
            accepted=True,
            error=None,
            reproduction_failed_before=True,
            unit_test_output="OK",
            reproduction_output="PASS",
        )

        mock_canary = MagicMock()
        # Canary check fails: error rate increased in canary traffic
        mock_canary.evaluate.return_value = MagicMock(
            healthy=False,
            verdict="FAIL",
            reason="Canary error rate 8.5% exceeds baseline by > 1.0%",
        )

        mock_deploy = MagicMock()

        executor = ActionExecutor(
            repo_root=self.repo,
            sandbox_verifier=mock_sandbox,
            canary_verifier=mock_canary,
            deploy_fn=mock_deploy,
        )

        proposal = FixProposal(
            type="patch",
            risk_tier="T2",
            diff="diff --git a/app.py b/app.py",
            rationale="Fix bug",
            expected_metric_effect="recover",
            target_service="orders",
        )

        res = executor.execute(proposal, incident_id="inc_canary_fail_001")

        self.assertFalse(res.success)
        self.assertTrue(res.aborted)
        self.assertEqual(res.failed_stage, "canary")
        self.assertEqual(res.stages_executed, ["sandbox", "canary"])
        self.assertIn("Canary", res.message)

        # STRICT ABORT: Promote must NEVER be called after canary failure
        mock_deploy.assert_not_called()

    def test_05_post_promotion_degradation_triggers_auto_rollback(self):
        """If post-promotion metrics degrade over baseline, AutoRollback is triggered."""
        mock_sandbox = MagicMock()
        mock_sandbox.verify.return_value = SandboxRun(
            verification=VerificationResult(
                tests_passed=True, repro_fixed=True, canary_healthy=True,
                metric_before=0.20, metric_after=0.20, verdict="PASS",
            ),
            accepted=True, error=None, reproduction_failed_before=True,
            unit_test_output="OK", reproduction_output="PASS",
        )
        mock_canary = MagicMock()
        mock_canary.evaluate.return_value = MagicMock(healthy=True, verdict="PASS", reason="")

        executor = ActionExecutor(
            repo_root=self.repo,
            release_manager=self.release_manager,
            sandbox_verifier=mock_sandbox,
            canary_verifier=mock_canary,
        )

        proposal = FixProposal(
            type="patch",
            risk_tier="T2",
            diff="diff --git a/app.py b/app.py",
            rationale="Fix bug",
            expected_metric_effect="recover",
            target_service="orders",
        )

        # Simulated post-promotion error rate of 0.35 (> baseline 0.20 + 0.01)
        res = executor.execute(
            proposal,
            incident_id="inc_degrade_001",
            post_promotion_error_rate=0.35,
        )

        self.assertFalse(res.success)
        self.assertTrue(res.aborted)
        self.assertEqual(res.failed_stage, "promote")
        self.assertEqual(res.stages_executed, ["sandbox", "canary", "promote"])
        self.assertIsNotNone(res.rollback_result)
        self.assertTrue(res.rollback_result.get("executed"))
        self.assertIn("auto-rollback", res.message.lower())

    def test_06_action_request_compatibility(self):
        """ActionExecutor accepts ActionRequest instances from safety.gate seamlessly."""
        mock_sandbox = MagicMock()
        mock_sandbox.verify.return_value = SandboxRun(
            verification=VerificationResult(
                tests_passed=True, repro_fixed=True, canary_healthy=True,
                metric_before=0.20, metric_after=0.002, verdict="PASS",
            ),
            accepted=True, error=None, reproduction_failed_before=True,
            unit_test_output="OK", reproduction_output="PASS",
        )
        mock_canary = MagicMock()
        mock_canary.evaluate.return_value = MagicMock(healthy=True, verdict="PASS", reason="")

        executor = ActionExecutor(
            repo_root=self.repo,
            release_manager=self.release_manager,
            sandbox_verifier=mock_sandbox,
            canary_verifier=mock_canary,
        )

        request = ActionRequest(
            incident_id="inc_req_001",
            action_type="patch",
            target_service="orders",
            risk_tier=RiskTier.T2,
            diff="diff --git a/app.py b/app.py",
            rationale="Safety-approved patch",
        )

        res = executor.execute(request, post_promotion_error_rate=0.002)

        self.assertTrue(res.success)
        self.assertEqual(res.action_type, "patch")
        self.assertEqual(res.risk_tier, "T2")
        self.assertEqual(res.stages_executed, ["sandbox", "canary", "promote"])


if __name__ == "__main__":
    unittest.main()
