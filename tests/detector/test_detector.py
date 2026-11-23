"""Unit Tests for NightShift Incident Detector and Telemetry Evaluator (Day 2 Task A1).

Verifies:
1. Parsing of Prometheus text format into structured MetricObservation.
2. Zero false-positive alerts during 10 minutes of healthy baseline traffic.
3. Error rate threshold enforcement (> 5% sustained for >= 30 seconds).
4. p95 latency threshold enforcement (> 3x baseline sustained for >= 30 seconds).
5. Strict incident deduplication by service and time window (repeating fault produces 0 duplicates).
6. Correlation of recent deployments/configs (< 30 minutes prior to incident).
7. Health recovery and automatic incident resolution.
8. 5-fault benchmark producing exactly 5 valid Incident objects.
"""

import json
from pathlib import Path
import tempfile
import unittest

from contracts.models import Incident
from detector.detector import IncidentDetector
from detector.evaluator import (
    MetricObservation,
    ServiceTelemetryEvaluator,
    parse_prometheus_text,
)


class TestIncidentDetector(unittest.TestCase):
    """Test suite for Telemetry Evaluator and Incident Detector."""

    def test_01_parse_prometheus_text(self):
        """parse_prometheus_text correctly parses metrics, errors, and histogram buckets."""
        prom_text = """
# HELP http_requests_total Total HTTP requests
# TYPE http_requests_total counter
http_requests_total{endpoint="/orders",method="POST",service="orders",status="200"} 80.0
http_requests_total{endpoint="/orders",method="POST",service="orders",status="500"} 20.0
# HELP http_request_duration_seconds HTTP latency
http_request_duration_seconds_bucket{endpoint="/orders",le="0.05",service="orders"} 70.0
http_request_duration_seconds_bucket{endpoint="/orders",le="0.1",service="orders"} 95.0
http_request_duration_seconds_bucket{endpoint="/orders",le="+Inf",service="orders"} 100.0
http_request_duration_seconds_count{endpoint="/orders",service="orders"} 100.0
http_request_duration_seconds_sum{endpoint="/orders",service="orders"} 4.5
"""
        obs = parse_prometheus_text(prom_text, service="orders")
        self.assertEqual(obs.total_requests, 100.0)
        self.assertEqual(obs.errors_5xx, 20.0)
        self.assertEqual(obs.duration_count, 100.0)
        self.assertEqual(obs.duration_sum, 4.5)
        self.assertIn(0.05, obs.histogram_buckets)
        self.assertIn(0.1, obs.histogram_buckets)

    def test_02_evaluator_healthy_baseline_zero_false_positives(self):
        """10 minutes of healthy baseline traffic (60 polls @ 10s) yields zero anomalies."""
        evaluator = ServiceTelemetryEvaluator(
            service="orders",
            error_rate_threshold=0.05,
            latency_multiplier_threshold=3.0,
            baseline_p95_latency=0.05,
            sustained_window_seconds=30.0,
        )

        t = 1700000000.0
        for tick in range(60):
            t += 10.0
            sample = MetricObservation(
                timestamp=t,
                total_requests=100.0 * (tick + 1),
                errors_5xx=0.0,
                p95_latency=0.020,
            )
            res = evaluator.add_observation(sample)
            self.assertFalse(res.is_anomalous)
            self.assertEqual(len(res.alerts), 0)
            self.assertEqual(len(res.symptoms), 0)

    def test_03_error_rate_threshold_and_sustained_window(self):
        """Error rate > 5% must persist for 30s before triggering an anomaly."""
        evaluator = ServiceTelemetryEvaluator(
            service="orders",
            error_rate_threshold=0.05,
            sustained_window_seconds=30.0,
        )

        t = 1700000000.0
        # t=0s: First anomalous sample (30% errors)
        res1 = evaluator.add_observation(
            MetricObservation(timestamp=t, total_requests=100.0, errors_5xx=30.0)
        )
        self.assertFalse(res1.is_anomalous, "Must not trigger at t=0s (not sustained for 30s)")

        # t=10s: 10s elapsed
        t += 10.0
        res2 = evaluator.add_observation(
            MetricObservation(timestamp=t, total_requests=200.0, errors_5xx=60.0)
        )
        self.assertFalse(res2.is_anomalous, "Must not trigger at t=10s")

        # t=20s: 20s elapsed
        t += 10.0
        res3 = evaluator.add_observation(
            MetricObservation(timestamp=t, total_requests=300.0, errors_5xx=90.0)
        )
        self.assertFalse(res3.is_anomalous, "Must not trigger at t=20s")

        # t=30s: 30s elapsed -> Anomalous threshold sustained!
        t += 10.0
        res4 = evaluator.add_observation(
            MetricObservation(timestamp=t, total_requests=400.0, errors_5xx=120.0)
        )
        self.assertTrue(res4.is_anomalous, "Must trigger at t=30s sustained duration")
        self.assertIn("OrdersHigh5xxRate", res4.alerts)
        self.assertEqual(res4.error_rate, 0.30)

    def test_04_latency_threshold_and_sustained_window(self):
        """p95 latency > 3x baseline must persist for 30s before triggering an anomaly."""
        evaluator = ServiceTelemetryEvaluator(
            service="payments",
            latency_multiplier_threshold=3.0,
            baseline_p95_latency=0.050,  # 50ms baseline -> threshold = 150ms
            sustained_window_seconds=30.0,
        )

        t = 1700000000.0
        for step in range(3):  # 0s, 10s, 20s
            res = evaluator.add_observation(
                MetricObservation(timestamp=t + (step * 10.0), total_requests=100.0 * (step + 1), errors_5xx=0.0, p95_latency=0.200)
            )
            self.assertFalse(res.is_anomalous)

        # 30s step
        res_sustained = evaluator.add_observation(
            MetricObservation(timestamp=t + 30.0, total_requests=400.0, errors_5xx=0.0, p95_latency=0.200)
        )
        self.assertTrue(res_sustained.is_anomalous)
        self.assertIn("PaymentsLatencySpike", res_sustained.alerts)

    def test_05_incident_deduplication(self):
        """Detector deduplicates repeated spikes within the dedupe window (10 minutes)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            detector = IncidentDetector(
                services=["orders"],
                sustained_window_seconds=10.0,
                dedupe_window_seconds=600.0,
                incidents_dir=Path(tmp_dir),
            )

            t = 1700000000.0
            # Sample 1 (t=0): prime
            detector.evaluate_sample("orders", MetricObservation(timestamp=t, total_requests=100.0, errors_5xx=25.0), now=t)

            # Sample 2 (t=15): sustained threshold met -> Incident opened!
            t += 15.0
            inc1, is_new1 = detector.evaluate_sample(
                "orders", MetricObservation(timestamp=t, total_requests=200.0, errors_5xx=50.0), now=t
            )
            self.assertIsNotNone(inc1)
            self.assertTrue(is_new1)
            self.assertEqual(inc1.service, "orders")

            # Subsequent spikes within 10 minutes: must be deduplicated
            for repeat in range(3):
                t += 10.0
                inc_rep, is_new_rep = detector.evaluate_sample(
                    "orders",
                    MetricObservation(
                        timestamp=t,
                        total_requests=300.0 + (repeat * 100.0),
                        errors_5xx=75.0 + (repeat * 25.0),
                    ),
                    now=t,
                )
                self.assertIsNotNone(inc_rep)
                self.assertFalse(is_new_rep, f"Repeat #{repeat} should not open new incident")
                self.assertEqual(inc_rep.id, inc1.id)

    def test_06_recent_changes_correlation(self):
        """Opened Incident correlates deployments and configs within 30 minutes of incident start."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            changes_file = Path(tmp_dir) / "changes.json"
            now_epoch = 1700000000.0
            changes_data = [
                {
                    "id": "dep_20261122_v1.0.1",
                    "service": "orders",
                    "timestamp": "2023-11-14T22:05:00+00:00", # ~15m prior
                    "version": "v1.0.1",
                },
                {
                    "id": "dep_old_v0.9.0",
                    "service": "orders",
                    "timestamp": "2023-11-14T10:00:00+00:00", # 12 hours prior (out of window)
                    "version": "v0.9.0",
                },
            ]
            changes_file.write_text(json.dumps(changes_data), encoding="utf-8")

            detector = IncidentDetector(
                services=["orders"],
                sustained_window_seconds=10.0,
                changes_path=changes_file,
                incidents_dir=Path(tmp_dir),
            )

            # Prime and trigger incident at 2023-11-14T22:13:20+00:00 (1700000000.0)
            detector.evaluate_sample("orders", MetricObservation(timestamp=now_epoch, total_requests=100.0, errors_5xx=30.0), now=now_epoch)
            inc, is_new = detector.evaluate_sample(
                "orders", MetricObservation(timestamp=now_epoch + 15.0, total_requests=200.0, errors_5xx=60.0), now=now_epoch + 15.0
            )

            self.assertIsNotNone(inc)
            self.assertTrue(is_new)
            self.assertTrue(any("dep_20261122_v1.0.1" in chg for chg in inc.recent_changes))
            self.assertFalse(any("dep_old_v0.9.0" in chg for chg in inc.recent_changes))

    def test_07_health_recovery_and_incident_resolution(self):
        """When metrics return to healthy baseline (<1% errors, low latency), active incident is resolved."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            detector = IncidentDetector(
                services=["orders"],
                sustained_window_seconds=10.0,
                incidents_dir=Path(tmp_dir),
            )

            t = 1700000000.0
            # Open incident
            detector.evaluate_sample("orders", MetricObservation(timestamp=t, total_requests=100.0, errors_5xx=30.0), now=t)
            inc, is_new = detector.evaluate_sample("orders", MetricObservation(timestamp=t + 15.0, total_requests=200.0, errors_5xx=60.0), now=t + 15.0)
            self.assertTrue(is_new)
            self.assertIn("orders", detector.active_incidents)

            # Recovery: healthy metrics arrive
            t += 30.0
            healthy_sample = MetricObservation(timestamp=t, total_requests=500.0, errors_5xx=60.0, p95_latency=0.020)
            recovered_inc, is_new_rec = detector.evaluate_sample("orders", healthy_sample, now=t)

            self.assertIsNone(recovered_inc)
            self.assertFalse(is_new_rec)
            self.assertNotIn("orders", detector.active_incidents)
            self.assertEqual(inc.status, "resolved")

    def test_08_five_faults_benchmark(self):
        """5 distinct fault injections produce exactly 5 valid Incident objects."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            detector = IncidentDetector(
                poll_interval=10.0,
                sustained_window_seconds=10.0,
                dedupe_window_seconds=300.0,
                incidents_dir=Path(tmp_dir),
            )

            fault_scenarios = [
                ("orders", 0.35, 0.025),
                ("payments", 0.15, 0.400),
                ("gateway", 0.40, 0.030),
                ("orders", 0.20, 0.300),
                ("payments", 0.25, 0.020),
            ]

            t = 1700000000.0
            opened_incidents = []

            for svc, err, lat in fault_scenarios:
                t += 400.0  # Exceed dedupe window
                # Sample 1: prime
                detector.evaluate_sample(svc, MetricObservation(timestamp=t, total_requests=100.0, errors_5xx=err*100, p95_latency=lat), now=t)
                # Sample 2: sustained
                t += 15.0
                inc, is_new = detector.evaluate_sample(
                    svc, MetricObservation(timestamp=t, total_requests=200.0, errors_5xx=err*200, p95_latency=lat), now=t
                )
                if inc and is_new:
                    opened_incidents.append(inc)

            self.assertEqual(len(opened_incidents), 5)
            for inc in opened_incidents:
                self.assertIsInstance(inc, Incident)
                self.assertTrue(inc.id.startswith("inc_"))
                self.assertGreater(len(inc.symptoms), 0)
                self.assertGreater(len(inc.alerts), 0)


if __name__ == "__main__":
    unittest.main()
