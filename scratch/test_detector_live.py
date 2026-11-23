"""Scratch verification script for NightShift Telemetry Detector (Day 2 Task A1).

Demonstrates and verifies:
1. False Positive Check: 10 minutes of simulated healthy traffic gives zero incidents.
2. Error Rate Threshold: Error rate > 5% sustained for 30s triggers an Incident within 60s.
3. Latency Threshold: p95 latency > 3x baseline sustained for 30s triggers an Incident.
4. Deduplication Check: Repeating the same fault 3 times opens exactly ONE incident.
5. 5-Fault Simulation: 5 distinct faults open exactly 5 incidents, each with valid Incident JSON.

Usage:
    python scratch/test_detector_live.py
"""

import sys
import tempfile
import time
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from contracts.models import Incident
from detector.detector import IncidentDetector
from detector.evaluator import MetricObservation


def run_detector_verification():
    print("=" * 75)
    print("NightShift AI On-Call Engineer: Telemetry Detector Test (Day 2 Task A1)")
    print("=" * 75)

    with tempfile.TemporaryDirectory() as tmp_dir:
        incidents_dir = Path(tmp_dir) / "incidents"
        incidents_dir.mkdir(parents=True, exist_ok=True)

        detector = IncidentDetector(
            services=["gateway", "orders", "payments"],
            poll_interval=10.0,
            error_rate_threshold=0.05,        # 5%
            latency_multiplier_threshold=3.0,   # 3x
            baseline_p95_latency=0.05,         # 50ms
            sustained_window_seconds=30.0,     # 30s
            dedupe_window_seconds=600.0,       # 10 minutes
            incidents_dir=incidents_dir,
        )

        base_time = 1700000000.0  # Simulated start time

        # ---------------------------------------------------------------------
        # Test 1: 10 Minutes of Healthy Traffic (Zero Incidents / Zero FP)
        # ---------------------------------------------------------------------
        print("\n[1/4] Simulating 10 minutes of healthy baseline traffic (60 polls @ 10s)...")
        opened_in_healthy = 0
        current_time = base_time

        for tick in range(60):
            current_time += 10.0
            # 100 requests, 0 errors, p95 = 20ms
            sample = MetricObservation(
                timestamp=current_time,
                total_requests=100.0 * (tick + 1),
                errors_5xx=0.0,
                p95_latency=0.020,
            )
            inc, is_new = detector.evaluate_sample("orders", sample, now=current_time)
            if inc and is_new:
                opened_in_healthy += 1

        print(f"      Total incidents opened during healthy period: {opened_in_healthy}")
        assert opened_in_healthy == 0, f"Expected 0 incidents during healthy traffic, got {opened_in_healthy}"
        print("      [PASS] False-positive check: Zero incidents opened during 10 min healthy baseline.")

        # ---------------------------------------------------------------------
        # Test 2: Error Rate Threshold (> 5% for 30s) & Deduplication (3 repeats)
        # ---------------------------------------------------------------------
        print("\n[2/4] Testing Error Rate Threshold (>5% for 30s) and Fault Deduplication...")
        
        # Inject fault: Error rate jumps to 30%
        # Poll 1 (elapsed 0s): Anomaly detected, but not yet sustained for 30s
        current_time += 10.0
        sample_f1 = MetricObservation(
            timestamp=current_time,
            total_requests=6100.0,
            errors_5xx=30.0,
            p95_latency=0.025,
        )
        inc1, is_new1 = detector.evaluate_sample("orders", sample_f1, now=current_time)
        assert inc1 is None, "Should not open incident at elapsed 0s (must be sustained for 30s)"
        print("      [PASS] t=10s (elapsed 0s): Anomaly observed, incident withheld pending 30s persistence.")

        # Poll 2 (elapsed 10s): Still under 30s sustained threshold
        current_time += 10.0
        sample_f2 = MetricObservation(
            timestamp=current_time,
            total_requests=6200.0,
            errors_5xx=60.0,
            p95_latency=0.025,
        )
        inc2, is_new2 = detector.evaluate_sample("orders", sample_f2, now=current_time)
        assert inc2 is None, "Should not open incident at elapsed 10s"
        print("      [PASS] t=20s (elapsed 10s): Anomaly persists, incident still withheld.")

        # Poll 3 (elapsed 20s): Still under 30s sustained threshold
        current_time += 10.0
        sample_f3 = MetricObservation(
            timestamp=current_time,
            total_requests=6300.0,
            errors_5xx=90.0,
            p95_latency=0.025,
        )
        inc3, is_new3 = detector.evaluate_sample("orders", sample_f3, now=current_time)
        assert inc3 is None, "Should not open incident at elapsed 20s"
        print("      [PASS] t=30s (elapsed 20s): Anomaly persists, incident still withheld.")

        # Poll 4 (elapsed 30s): Exactly 30s elapsed -> Incident MUST OPEN!
        current_time += 10.0
        sample_f4 = MetricObservation(
            timestamp=current_time,
            total_requests=6400.0,
            errors_5xx=120.0,
            p95_latency=0.025,
        )
        incident_orders, is_new4 = detector.evaluate_sample("orders", sample_f4, now=current_time)
        assert incident_orders is not None, "Incident must be opened at elapsed 30s sustained!"
        assert is_new4 is True, "Must be flagged as a new incident"
        print(f"      [PASS] t=40s (elapsed 30s): Incident opened: {incident_orders.id} on '{incident_orders.service}'.")
        print(f"             Alerts: {incident_orders.alerts}")
        print(f"             Symptoms: {incident_orders.symptoms}")

        # Deduplication Check: Repeat the fault 3 times in subsequent polls
        print("      Testing repeated fault pulses (deduplication check)...")
        for repeat in range(1, 4):
            current_time += 10.0
            sample_repeat = MetricObservation(
                timestamp=current_time,
                total_requests=6400.0 + (repeat * 100.0),
                errors_5xx=120.0 + (repeat * 30.0),
                p95_latency=0.025,
            )
            rep_inc, rep_is_new = detector.evaluate_sample("orders", sample_repeat, now=current_time)
            assert rep_inc is not None
            assert rep_is_new is False, f"Repeat #{repeat} created a duplicate incident!"
        print("      [PASS] Deduplication: Repeating fault 3 times produced ZERO duplicate incidents.")

        # ---------------------------------------------------------------------
        # Test 3: Latency Threshold (> 3x baseline for 30s)
        # ---------------------------------------------------------------------
        print("\n[3/4] Testing Latency Spike Threshold (> 3x baseline)...")
        # Payments service has baseline 50ms. Latency spikes to 250ms (5x baseline)
        lat_inc = None
        lat_is_new = False
        for t_step in range(4): # 0s, 10s, 20s, 30s
            current_time += 10.0
            lat_sample = MetricObservation(
                timestamp=current_time,
                total_requests=100.0 * (t_step + 1),
                errors_5xx=0.0,
                p95_latency=0.250, # 250ms
            )
            lat_inc, lat_is_new = detector.evaluate_sample("payments", lat_sample, now=current_time)

        assert lat_inc is not None, "Latency incident must open after 30s sustained"
        assert lat_is_new is True
        assert "PaymentsLatencySpike" in lat_inc.alerts
        print(f"      [PASS] Latency incident opened: {lat_inc.id} on '{lat_inc.service}'.")
        print(f"             Alerts: {lat_inc.alerts}")

        # ---------------------------------------------------------------------
        # Test 4: 5 Faults Injected Simulation (Total = 5 Incidents)
        # ---------------------------------------------------------------------
        print("\n[4/4] Simulating 5 distinct fault injections...")
        # Reset detector for a clean multi-fault benchmark
        bench_detector = IncidentDetector(
            poll_interval=10.0,
            sustained_window_seconds=10.0, # Fast sustained window for benchmark
            dedupe_window_seconds=300.0,
            incidents_dir=incidents_dir,
        )

        simulated_faults = [
            ("orders", "fault_001_bad_deploy", 0.35, 0.025),
            ("payments", "fault_002_timeout", 0.15, 0.400),
            ("gateway", "fault_003_upstream_502", 0.40, 0.030),
            ("orders", "fault_004_db_pool_leak", 0.20, 0.300),
            ("payments", "fault_005_auth_expired", 0.25, 0.020),
        ]

        opened_count = 0
        b_time = base_time + 10000.0

        for idx, (svc, fault_id, err_rate, lat) in enumerate(simulated_faults, 1):
            # Advance time by 400s between faults to exceed dedupe window
            b_time += 400.0
            # Sample 1: prime evaluator
            s1 = MetricObservation(timestamp=b_time, total_requests=100.0, errors_5xx=err_rate*100, p95_latency=lat)
            bench_detector.evaluate_sample(svc, s1, now=b_time)
            # Sample 2: sustained threshold met
            b_time += 15.0
            s2 = MetricObservation(timestamp=b_time, total_requests=200.0, errors_5xx=err_rate*200, p95_latency=lat)
            inc, is_new = bench_detector.evaluate_sample(svc, s2, now=b_time)

            if inc and is_new:
                opened_count += 1
                assert isinstance(inc, Incident)
                assert inc.service == svc
                print(f"      Fault #{idx} ({fault_id}): Opened incident {inc.id} on '{svc}'.")

        print(f"\nTotal incidents opened across 5 faults: {opened_count}")
        assert opened_count == 5, f"Expected exactly 5 incidents, got {opened_count}"
        print("      [PASS] Exactly 5 incidents opened for 5 injected faults.")

        print("\n" + "=" * 75)
        print("SUCCESS: Day 2 Task A1 Verification Passed!")
        print("  • 10 minutes of healthy traffic: 0 false positives.")
        print("  • Error rate (>5% for 30s) and latency (>3x for 30s) trigger properly.")
        print("  • Repeating fault 3 times produced 0 duplicates.")
        print("  • 5 faults produced exactly 5 valid Incident JSON records.")
        print("=" * 75)


if __name__ == "__main__":
    run_detector_verification()
