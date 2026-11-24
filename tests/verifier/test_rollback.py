"""Unit tests for Automatic Rollback Guard (Day 5 Task A3)."""

import logging
import tempfile
import unittest
from pathlib import Path

from deployer.changes import ChangeLog
from deployer.release_manager import ReleaseManager
from deployer.runners import NoopRunner
from verifier.rollback import (
    AutoRollbackGuard,
    RollbackDecision,
    DEFAULT_ROLLBACK_WINDOW_SECONDS,
)


class TestAutoRollbackGuard(unittest.TestCase):
    def test_default_window_is_sixty_seconds_or_less(self):
        """Rollback decision window must be strictly 60 seconds or less."""
        self.assertEqual(DEFAULT_ROLLBACK_WINDOW_SECONDS, 60.0)
        guard = AutoRollbackGuard(service="orders", baseline_error_rate=0.03)
        self.assertEqual(guard.window_seconds, 60.0)

        # Invalid window (> 60s or <= 0s) must be rejected
        with self.assertRaises(ValueError):
            AutoRollbackGuard(service="orders", baseline_error_rate=0.03, window_seconds=65.0)
        with self.assertRaises(ValueError):
            AutoRollbackGuard(service="orders", baseline_error_rate=0.03, window_seconds=0)

    def test_deliberately_bad_fix_triggers_rollback_within_60s_with_reason(self):
        """Task A3 Criterion: Deliberately bad fix triggers rollback in <= 60s and log states the reason."""
        rollback_calls = []

        def mock_rollback(service: str, reason: str):
            rollback_calls.append({"service": service, "reason": reason})
            return {"status": "ok", "service": service, "rolled_back": True}

        # Simulated clock
        current_time = 1000.0

        def time_fn():
            return current_time

        def sleep_fn(sec):
            nonlocal current_time
            current_time += sec

        # Baseline error rate was 5% (0.05)
        guard = AutoRollbackGuard(
            service="orders",
            baseline_error_rate=0.05,
            rollback_fn=mock_rollback,
            window_seconds=60.0,
            poll_interval_seconds=1.0,
            bad_samples_threshold=2,
            time_fn=time_fn,
            sleep_fn=sleep_fn,
        )

        # Deliberately bad fix produces 12% error rate (worse than 5%)
        def bad_metric_sampler():
            return 0.12

        with self.assertLogs("nightshift.verifier.rollback", level=logging.WARNING) as cm:
            decision: RollbackDecision = guard.monitor(bad_metric_sampler)

        # 1. Rollback must have occurred
        self.assertTrue(decision.rolled_back)
        self.assertEqual(decision.service, "orders")

        # 2. Must happen within 60s
        self.assertLessEqual(decision.decision_time_seconds, 60.0)
        self.assertGreater(decision.decision_time_seconds, 0.0)

        # 3. Log and reason must state the exact cause
        self.assertIn("is worse than baseline", decision.reason)
        self.assertIn("12.00%", decision.reason)
        self.assertIn("5.00%", decision.reason)
        self.assertIn("automatic rollback executed in", decision.reason)

        # Check log output
        log_text = "\n".join(cm.output)
        self.assertIn("AUTOMATIC ROLLBACK TRIGGERED", log_text)
        self.assertIn("orders", log_text)

        # Check rollback handler receipt
        self.assertEqual(len(rollback_calls), 1)
        self.assertEqual(rollback_calls[0]["service"], "orders")
        self.assertEqual(rollback_calls[0]["reason"], decision.reason)

    def test_good_fix_does_not_trigger_rollback(self):
        """A good fix reducing error rate does not trigger rollback."""
        rollback_called = False

        def mock_rollback(_service: str, _reason: str):
            nonlocal rollback_called
            rollback_called = True

        current_time = 1000.0

        def time_fn():
            return current_time

        def sleep_fn(sec):
            nonlocal current_time
            current_time += sec

        guard = AutoRollbackGuard(
            service="orders",
            baseline_error_rate=0.05,
            rollback_fn=mock_rollback,
            window_seconds=60.0,
            poll_interval_seconds=5.0,
            time_fn=time_fn,
            sleep_fn=sleep_fn,
        )

        # Good fix drops error rate to 0.1% (<5%)
        def good_metric_sampler():
            return 0.001

        decision = guard.monitor(good_metric_sampler)

        self.assertFalse(decision.rolled_back)
        self.assertFalse(rollback_called)
        self.assertLessEqual(decision.decision_time_seconds, 65.0)
        self.assertIn("Promotion safe", decision.reason)

    def test_integration_with_release_manager(self):
        """AutoRollbackGuard invokes ReleaseManager.rollback and restores previous release."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            repo = tmp / "repo"
            repo.mkdir()
            import subprocess
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "--allow-empty", "-qm", "v1"], cwd=repo, check=True)
            v1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()

            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e", "commit", "--allow-empty", "-qm", "v2-bad-fix"], cwd=repo, check=True)
            v2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()

            changelog = ChangeLog(tmp / "changes.jsonl")
            runner = NoopRunner()
            rm = ReleaseManager(
                repo_dir=repo,
                state_path=tmp / "deployer_state.json",
                changelog=changelog,
                runner=runner,
            )

            # Deploy v1, then deploy v2
            rm.deploy("orders", v1, author="ci", message="deploy v1")
            rm.deploy("orders", v2, author="ci", message="deploy candidate fix")
            self.assertEqual(rm.current("orders"), v2)

            # Attach AutoRollbackGuard to ReleaseManager
            guard = AutoRollbackGuard(
                service="orders",
                baseline_error_rate=0.04,
                release_manager=rm,
                window_seconds=30.0,
                bad_samples_threshold=1,
            )

            # Simulated post-promotion metrics show 15% error (severe degradation)
            decision = guard.monitor(lambda: 0.15, timeout=5.0)

            # Verification:
            self.assertTrue(decision.rolled_back)
            self.assertIn("is worse than baseline", decision.reason)

            # Service is automatically restored to v1!
            self.assertEqual(rm.current("orders"), v1)

            # Changelog records the automatic rollback event
            recent_changes = changelog.list(service="orders")
            event_types = [c["type"] for c in recent_changes]
            self.assertIn("rollback", event_types)


if __name__ == "__main__":
    unittest.main()
