"""Unit tests for Production Recovery Checker (Day 5 Task A2)."""

import unittest
from datetime import datetime, timezone
from verifier.recovery import (
    ProductionRecoveryChecker,
    RecoveryResult,
    RecoveryState,
    DEFAULT_REQUIRED_STABLE_SECONDS,
    DEFAULT_TARGET_ERROR_RATE,
)


class TestProductionRecoveryChecker(unittest.TestCase):
    def test_default_constants(self):
        """Default target error rate is 1% (< 0.01) and stable window is 60s."""
        self.assertEqual(DEFAULT_TARGET_ERROR_RATE, 0.01)
        self.assertEqual(DEFAULT_REQUIRED_STABLE_SECONDS, 60.0)

    def test_stopwatch_accuracy_in_three_runs(self):
        """Task A2 criterion: recovered_at is within 5s of stopwatch reading in 3 runs."""
        for run_idx in range(1, 4):
            with self.subTest(run=run_idx):
                # Simulated clock state
                current_time = 1700000000.0 + (run_idx * 1000)

                def time_fn():
                    return current_time

                def sleep_fn(sec):
                    nonlocal current_time
                    current_time += sec

                checker = ProductionRecoveryChecker(
                    target_error_rate=0.01,
                    required_stable_seconds=60.0,
                    poll_interval_seconds=1.0,
                    time_fn=time_fn,
                    sleep_fn=sleep_fn,
                )

                # Simulate incident: faulty for 10s, then drops to 0.002 (< 1%) at stopwatch_drop_time
                faulty_duration = 10.0 + run_idx * 5.0
                start_clock = current_time
                stopwatch_expected_recovery = start_clock + faulty_duration

                def metric_sampler():
                    elapsed = current_time - start_clock
                    if elapsed < faulty_duration:
                        return 0.08  # 8% error rate (unhealthy)
                    return 0.003  # 0.3% error rate (<1%, healthy)

                result: RecoveryResult = checker.watch(metric_sampler, timeout=200.0)

                self.assertTrue(result.recovered)
                self.assertIsNotNone(result.recovered_at)

                # Parse recovered_at timestamp
                dt = datetime.fromisoformat(result.recovered_at)
                recovered_epoch = dt.timestamp()

                # Difference between stopwatch reading and recorded recovered_at must be within 5 seconds
                delta = abs(recovered_epoch - stopwatch_expected_recovery)
                self.assertLessEqual(
                    delta,
                    5.0,
                    f"Run {run_idx}: delta {delta:.2f}s exceeded 5s stopwatch tolerance! (recorded {recovered_epoch}, stopwatch {stopwatch_expected_recovery})",
                )
                self.assertGreaterEqual(result.stable_duration_seconds, 60.0)

    def test_transient_dip_does_not_trigger_premature_recovery(self):
        """Transient error drop resetting before 60s must reset the timer."""
        current_time = 1700000000.0

        def time_fn():
            return current_time

        def sleep_fn(sec):
            nonlocal current_time
            current_time += sec

        checker = ProductionRecoveryChecker(
            target_error_rate=0.01,
            required_stable_seconds=60.0,
            poll_interval_seconds=1.0,
            time_fn=time_fn,
            sleep_fn=sleep_fn,
        )

        # Timeline:
        # 0s - 10s: 5% error
        # 10s - 30s: 0.5% error (20s dip, NOT enough for 60s)
        # 30s - 40s: 4% error spike (resets timer)
        # 40s - 110s: 0.2% error (sustained 70s -> RECOVERY achieved at 40s, confirmed at 100s)
        start_clock = current_time

        def metric_sampler():
            elapsed = current_time - start_clock
            if elapsed < 10.0:
                return 0.05
            elif elapsed < 30.0:
                return 0.005  # dip
            elif elapsed < 40.0:
                return 0.04   # spike
            else:
                return 0.002  # true recovery

        result = checker.watch(metric_sampler, timeout=200.0)
        self.assertTrue(result.recovered)

        dt = datetime.fromisoformat(result.recovered_at)
        recovered_epoch = dt.timestamp()

        # The true recovery start was at 40s after start
        true_recovery_start = start_clock + 40.0
        self.assertAlmostEqual(recovered_epoch, true_recovery_start, delta=2.0)

    def test_unrecovered_metrics_timeout(self):
        """If metrics remain above 1%, watch times out and returns recovered=False."""
        current_time = 1700000000.0

        def time_fn():
            return current_time

        def sleep_fn(sec):
            nonlocal current_time
            current_time += sec

        checker = ProductionRecoveryChecker(
            target_error_rate=0.01,
            required_stable_seconds=60.0,
            timeout_seconds=120.0,
            poll_interval_seconds=5.0,
            time_fn=time_fn,
            sleep_fn=sleep_fn,
        )

        def metric_sampler():
            return 0.035  # Constant 3.5% error rate (unhealthy)

        result = checker.watch(metric_sampler)
        self.assertFalse(result.recovered)
        self.assertIsNone(result.recovered_at)
        self.assertIn("Timeout", result.reason)

    def test_real_clock_stopwatch_accuracy(self):
        """A brief real-clock test using real time.time and time.sleep."""
        import time

        checker = ProductionRecoveryChecker(
            target_error_rate=0.01,
            required_stable_seconds=1.5,
            timeout_seconds=10.0,
            poll_interval_seconds=0.2,
        )

        stopwatch_start = time.time()
        # Sleep 0.4s while failing
        time.sleep(0.4)
        stopwatch_drop = time.time()

        def sampler():
            return 0.002  # Healthy from stopwatch_drop onwards

        result = checker.watch(sampler)
        self.assertTrue(result.recovered)
        self.assertIsNotNone(result.recovered_at)

        dt = datetime.fromisoformat(result.recovered_at)
        delta = abs(dt.timestamp() - stopwatch_drop)
        self.assertLessEqual(delta, 1.0, f"Real-clock stopwatch delta {delta:.3f}s was not within 1s")


if __name__ == "__main__":
    unittest.main()
