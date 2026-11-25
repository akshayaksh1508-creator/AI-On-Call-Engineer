"""Unit tests for Day 8 Tasks A1-A4 (Benchmark v1, Triage, Stability, Regression Suite).

Verifies:
1. Task A1: Benchmark v1 runs 15 training faults (leaving 5 held-out untouched), writes v1.json,
   and re-running produces results within <= 1 incident of the first run.
2. Task A2: Failure triage sheet assigns valid labels and one-line causes to all failures,
   and label counts sum strictly to total failures.
3. Task A3: Hardened resets, detector, and canary window achieve < 10% flaky rate across 3 runs.
4. Task A4: Regression suite re-runs previously passing faults under 30 minutes and catches new failures.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bench.regression import RegressionSuite, extract_passing_faults
from bench.runner import BenchmarkRunner
from bench.triage import VALID_TRIAGE_LABELS, build_triage_sheet, write_triage_artifacts
from bench.v1_runner import get_training_fault_ids, run_benchmark_v1
from contracts.models import RunRecord
from verifier.canary import CanaryMetrics, CanaryVerifier


class TestDay8BenchmarkAndRegression(unittest.TestCase):
    """Test suite for Day 8 Tasks A1 to A4."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_benchmark_v1_fifteen_training_faults_and_repeatability(self) -> None:
        """Exit criterion A1: v1 runs 15 training faults and re-run is within 1 incident."""
        training_ids, _ = get_training_fault_ids()
        self.assertEqual(len(training_ids), 15)
        self.assertTrue(all(not fid.startswith("fault_016") and not fid.startswith("fault_020") for fid in training_ids))

        v1_a = self.out_dir / "v1_a.json"
        v1_b = self.out_dir / "v1_b.json"

        res_a = run_benchmark_v1(out_path=v1_a)
        res_b = run_benchmark_v1(out_path=v1_b)

        self.assertTrue(v1_a.exists())
        self.assertEqual(res_a["training_fault_count"], 15)
        self.assertEqual(res_a["held_out_untouched"], 5)
        self.assertEqual(len(res_a["runs"]), 15)

        diff_fix_ok = abs(res_a["summary"]["fix_ok_count"] - res_b["summary"]["fix_ok_count"])
        self.assertLessEqual(diff_fix_ok, 1, "Re-running Benchmark v1 must be within 1 incident")

    def test_02_failure_triage_sheet_labels_and_counts_sum_to_total(self) -> None:
        """Exit criterion A2: Every failure has a valid label & cause; label counts sum to total."""
        v1_path = self.out_dir / "v1.json"
        payload = run_benchmark_v1(out_path=v1_path)
        triage = write_triage_artifacts(v1_path)

        self.assertGreater(triage["total_failures"], 0)
        self.assertEqual(len(triage["failures"]), triage["total_failures"])
        self.assertEqual(sum(triage["counts_by_label"].values()), triage["total_failures"])

        for failure in triage["failures"]:
            self.assertIn(failure["label"], VALID_TRIAGE_LABELS)
            self.assertTrue(failure["cause"].strip())
            self.assertNotIn("\n", failure["cause"])

        self.assertTrue((self.out_dir / "triage_v1.json").exists())
        self.assertTrue((self.out_dir / "triage_v1.md").exists())

        # Verify infrastructure label also counts cleanly
        synthetic = {
            "runs": [
                {
                    "fault_id": "fault_infra_test",
                    "status": "infra_error",
                    "classification_reason": "Service killed mid-run",
                    "run_record": {"incident_id": "inc_x", "fix_ok": False},
                }
            ]
        }
        t_syn = build_triage_sheet(synthetic)
        self.assertEqual(t_syn["counts_by_label"]["infrastructure"], 1)
        self.assertEqual(sum(t_syn["counts_by_label"].values()), t_syn["total_failures"])

    def test_03_hardened_reset_and_canary_keep_flaky_rate_below_10_percent(self) -> None:
        """Exit criterion A3: Re-running affected faults 3 times each yields flaky rate < 10%."""
        reset_calls = [0]

        def flaky_once_reset(_fid: str) -> None:
            reset_calls[0] += 1
            # First teardown fails transiently; hardened _reset_with_retry absorbs it!
            if reset_calls[0] == 1:
                raise OSError("Transient file lock on reset")

        def ok_orchestrate(fid: str) -> RunRecord:
            return RunRecord(
                incident_id=f"inc_{fid}",
                fault_id=fid,
                t_detect=5.0,
                t_rca=1.0,
                t_fix=1.0,
                t_verified=2.0,
                rca_correct_top1=True,
                rca_correct_top3=True,
                fix_ok=True,
            )

        runner = BenchmarkRunner(
            reset_fn=flaky_once_reset,
            orchestrate_fn=ok_orchestrate,
            confirm_healthy_seconds=0.005,
            health_poll_interval=0.002,
        )

        affected = ["fault_001_bad_deploy", "fault_002_off_by_one", "fault_003_wrong_status_code"]
        total_attempts = 0
        flaky_failures = 0
        for fid in affected:
            for _ in range(3):
                total_attempts += 1
                entry = runner.run_fault(fid)
                if entry.status != "pass":
                    flaky_failures += 1

        flaky_rate = flaky_failures / total_attempts
        self.assertLess(flaky_rate, 0.10, f"Flaky rate {flaky_rate:.2%} exceeded 10%")

        # Canary low-sample jitter guard check
        canary = CanaryVerifier(min_canary_requests=5)
        base = CanaryMetrics(total_requests=100, error_count=0, error_rate=0.0, mean_latency_ms=25.0, p95_latency_ms=40.0)
        low_jitter = CanaryMetrics(total_requests=3, error_count=1, error_rate=0.3333, mean_latency_ms=25.0, p95_latency_ms=40.0)
        self.assertTrue(canary.evaluate(base, low_jitter).healthy)

    def test_04_regression_suite_passes_under_30_min_and_reports_new_failure(self) -> None:
        """Exit criterion A4: Regression suite runs < 30 min and catches any newly broken fault."""
        v1_path = self.out_dir / "v1.json"
        run_benchmark_v1(out_path=v1_path)
        passing_faults = extract_passing_faults(v1_path)
        self.assertGreater(len(passing_faults), 0)

        suite = RegressionSuite()
        clean_report = suite.run(passing_faults, out_path=self.out_dir / "regression_clean.json")
        self.assertTrue(clean_report.passed)
        self.assertEqual(clean_report.regressions, [])
        self.assertTrue(clean_report.within_budget)
        self.assertLess(clean_report.elapsed_seconds, 1800.0)

        # Inject a regression into one previously passing fault
        target_broken = passing_faults[0]

        def broken_orchestrate(fid: str):
            if fid == target_broken:
                return {
                    "run_record": RunRecord(
                        incident_id=f"inc_reg_{fid}",
                        fault_id=fid,
                        t_detect=5.0,
                        t_rca=1.0,
                        t_fix=1.0,
                        t_verified=2.0,
                        rca_correct_top1=True,
                        rca_correct_top3=True,
                        fix_ok=False,
                    ),
                    "success": False,
                    "error_message": "Regression introduced in prompt",
                }
            return {
                "run_record": RunRecord(
                    incident_id=f"inc_ok_{fid}",
                    fault_id=fid,
                    t_detect=5.0,
                    t_rca=1.0,
                    t_fix=1.0,
                    t_verified=2.0,
                    rca_correct_top1=True,
                    rca_correct_top3=True,
                    fix_ok=True,
                ),
                "success": True,
            }

        reg_suite = RegressionSuite(orchestrate_fn=broken_orchestrate)
        broken_report = reg_suite.run(passing_faults)
        self.assertFalse(broken_report.passed)
        self.assertEqual(broken_report.regressions, [target_broken])


if __name__ == "__main__":
    unittest.main()
