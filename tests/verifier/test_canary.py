"""Unit tests for Canary Deployment Verifier (Day 5 Task A1)."""

import unittest
from verifier.canary import (
    CanaryMetrics,
    CanaryVerifier,
    PASS_RULE,
    DEFAULT_TRAFFIC_WEIGHT,
    DEFAULT_WINDOW_SECONDS,
)


class TestCanaryVerifier(unittest.TestCase):
    def setUp(self):
        self.verifier = CanaryVerifier()

    def test_pass_rule_is_explicitly_defined(self):
        """Pass rule must state: error rate no more than baseline plus 1%."""
        self.assertEqual(PASS_RULE, "canary_error_rate <= baseline_error_rate + 0.01")
        baseline = CanaryMetrics(total_requests=100, error_count=2, error_rate=0.02, mean_latency_ms=25.0, p95_latency_ms=40.0)
        canary = CanaryMetrics(total_requests=20, error_count=0, error_rate=0.00, mean_latency_ms=24.0, p95_latency_ms=38.0)
        res = self.verifier.evaluate(baseline, canary)
        self.assertEqual(res.pass_rule, PASS_RULE)

    def test_good_fix_marked_healthy(self):
        """A good fix reducing or maintaining error rate is marked HEALTHY."""
        baseline = CanaryMetrics(total_requests=1000, error_count=50, error_rate=0.05, mean_latency_ms=30.0, p95_latency_ms=50.0)
        # Canary has 0 errors (recovery)
        canary = CanaryMetrics(total_requests=150, error_count=0, error_rate=0.00, mean_latency_ms=28.0, p95_latency_ms=45.0)

        result = self.verifier.evaluate(baseline, canary)
        self.assertTrue(result.healthy)
        self.assertEqual(result.verdict, "HEALTHY")
        self.assertIn("within pass rule", result.reason)

    def test_bad_fix_marked_unhealthy(self):
        """A fix causing canary error rate to exceed baseline + 1% is marked UNHEALTHY."""
        baseline = CanaryMetrics(total_requests=1000, error_count=20, error_rate=0.02, mean_latency_ms=25.0, p95_latency_ms=40.0)
        # Canary has 5% error rate (delta +3%, exceeds +1% limit)
        canary = CanaryMetrics(total_requests=150, error_count=8, error_rate=0.0533, mean_latency_ms=26.0, p95_latency_ms=42.0)

        result = self.verifier.evaluate(baseline, canary)
        self.assertFalse(result.healthy)
        self.assertEqual(result.verdict, "UNHEALTHY")
        self.assertIn("exceeded baseline", result.reason)

    def test_boundary_error_delta_at_one_percent(self):
        """Error rate delta of exactly +1.0% passes; +1.1% fails."""
        baseline = CanaryMetrics(total_requests=1000, error_count=50, error_rate=0.05, mean_latency_ms=30.0, p95_latency_ms=50.0)

        # Exactly +1.0% (canary = 6.0%) -> PASS
        canary_at_boundary = CanaryMetrics(total_requests=200, error_count=12, error_rate=0.06, mean_latency_ms=30.0, p95_latency_ms=50.0)
        res_boundary = self.verifier.evaluate(baseline, canary_at_boundary)
        self.assertTrue(res_boundary.healthy)
        self.assertEqual(res_boundary.verdict, "HEALTHY")

        # +1.1% (canary = 6.1%) -> FAIL
        canary_over_boundary = CanaryMetrics(total_requests=200, error_count=13, error_rate=0.061, mean_latency_ms=30.0, p95_latency_ms=50.0)
        res_over = self.verifier.evaluate(baseline, canary_over_boundary)
        self.assertFalse(res_over.healthy)
        self.assertEqual(res_over.verdict, "UNHEALTHY")

    def test_canary_traffic_weight_constraints(self):
        """Traffic weight must be between 10% and 20% (0.10 to 0.20)."""
        self.assertEqual(DEFAULT_TRAFFIC_WEIGHT, 0.15)
        # Valid weights in range 10-20%
        v10 = CanaryVerifier(traffic_weight=0.10)
        self.assertEqual(v10.traffic_weight, 0.10)
        v20 = CanaryVerifier(traffic_weight=0.20)
        self.assertEqual(v20.traffic_weight, 0.20)

        # Invalid weights outside range
        with self.assertRaises(ValueError):
            CanaryVerifier(traffic_weight=0.05)  # 5% is too low
        with self.assertRaises(ValueError):
            CanaryVerifier(traffic_weight=0.30)  # 30% is too high

    def test_canary_observation_window_defaults(self):
        """Default observation window is 60 seconds and must be positive."""
        self.assertEqual(DEFAULT_WINDOW_SECONDS, 60.0)
        self.assertEqual(self.verifier.window_seconds, 60.0)
        with self.assertRaises(ValueError):
            CanaryVerifier(window_seconds=0)
        with self.assertRaises(ValueError):
            CanaryVerifier(window_seconds=-10)

    def test_canary_latency_degradation_detected(self):
        """Significant latency degradation (>1.5x baseline) flags canary as UNHEALTHY."""
        baseline = CanaryMetrics(total_requests=500, error_count=5, error_rate=0.01, mean_latency_ms=20.0, p95_latency_ms=35.0)
        # Zero errors but latency jumps to 40ms (2.0x baseline, exceeding 1.5x threshold)
        canary_slow = CanaryMetrics(total_requests=100, error_count=0, error_rate=0.00, mean_latency_ms=40.0, p95_latency_ms=75.0)

        res = self.verifier.evaluate(baseline, canary_slow)
        self.assertFalse(res.healthy)
        self.assertEqual(res.verdict, "UNHEALTHY")
        self.assertIn("latency", res.reason.lower())

    def test_simulated_traffic_loop_distribution(self):
        """Simulated traffic loop routes 10-20% requests to canary and measures verdict."""
        verifier = CanaryVerifier(traffic_weight=0.15, window_seconds=60.0)

        def mock_baseline():
            # Baseline experiencing 10% errors
            import random
            err = random.random() < 0.10
            return (not err, 25.0)

        def mock_good_canary():
            # Fixed canary with 0% errors
            return (True, 24.0)

        result = verifier.run_simulated_traffic(
            mock_baseline,
            mock_good_canary,
            total_requests=400,
        )

        # Check request distribution
        total = result.baseline_metrics.total_requests + result.canary_metrics.total_requests
        self.assertEqual(total, 400)
        canary_fraction = result.canary_metrics.total_requests / total
        # Probability for 15% traffic in 400 requests should comfortably be between 8% and 25%
        self.assertGreater(canary_fraction, 0.08)
        self.assertLess(canary_fraction, 0.25)

        # Good canary should be healthy
        self.assertTrue(result.healthy)
        self.assertEqual(result.verdict, "HEALTHY")


if __name__ == "__main__":
    unittest.main()
