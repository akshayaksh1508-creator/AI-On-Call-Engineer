"""Unit tests for Day 8 Tasks B1-B4 (RCA Improvements, Calibration, Cross-Service, Failure Analysis).

Verifies:
1. Task B1 & Day 8 Gate: Re-running failed incidents logs per-change deltas, passes regression
   checks, and meets RCA Top-3 >= 70% and Fix Success >= 55%.
2. Task B2: Confidence calibration bins results and raises threshold when >= 0.8 bin accuracy < 80%.
3. Task B3: Cross-service improvements achieve >= 50% Top-3 accuracy on cross-service faults.
4. Task B4: Draft failure-analysis table names incident, cause of failure, and proposed change per row.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.cross_service import CrossServiceAnalyzer
from agent.rca_improvements import apply_day8_improvements_and_log_deltas
from bench.triage import write_triage_artifacts
from bench.v1_runner import run_benchmark_v1
from reporter.failure_analysis import write_failure_analysis_table
from safety.calibration import calibrate_confidence, format_calibration_markdown


class TestDay8TasksB1ToB4(unittest.TestCase):
    """Test suite for Day 8 Person B tasks (B1-B4)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_rca_improvements_log_deltas_no_regressions_and_meet_gate(self) -> None:
        """Exit criterion B1 & Day 8 Gate: Deltas logged, zero regressions, Top-3 >= 70%, Fix >= 55%."""
        v1_path = self.out_dir / "v1.json"
        v2_path = self.out_dir / "v2.json"
        delta_path = self.out_dir / "delta.json"

        run_benchmark_v1(out_path=v1_path)
        delta_doc = apply_day8_improvements_and_log_deltas(
            v1_path=v1_path,
            v2_out_path=v2_path,
            delta_out_path=delta_path,
        )

        self.assertTrue(delta_path.exists())
        self.assertGreater(len(delta_doc["deltas"]), 0)
        for d in delta_doc["deltas"]:
            self.assertTrue(d["regression_passed"], f"Regression failed after {d['change_id']}")

        self.assertGreater(delta_doc["final_fix_ok"], delta_doc["baseline_fix_ok"])
        self.assertTrue(delta_doc["gate_rca_top3_met"], f"RCA Top-3 < 70%: {delta_doc['final_rca_top3_accuracy']}")
        self.assertTrue(delta_doc["gate_fix_success_met"], f"Fix rate < 55%: {delta_doc['final_fix_success_rate']}")

    def test_02_confidence_calibration_table_and_threshold_adjustment(self) -> None:
        """Exit criterion B2: >= 0.8 bin requires >= 80% accuracy; otherwise threshold is raised."""
        # Case 1: Well-calibrated (>= 0.8 bin has 5/5 = 100% accuracy)
        good_samples = [
            {"confidence": 0.40, "correct": False},
            {"confidence": 0.65, "correct": True},
            {"confidence": 0.72, "correct": False},
            {"confidence": 0.85, "correct": True},
            {"confidence": 0.88, "correct": True},
            {"confidence": 0.90, "correct": True},
            {"confidence": 0.92, "correct": True},
            {"confidence": 0.95, "correct": True},
        ]
        ok_report = calibrate_confidence(good_samples, current_threshold=0.80)
        self.assertTrue(ok_report.calibrated_ok)
        self.assertFalse(ok_report.threshold_raised)
        self.assertEqual(ok_report.recommended_threshold, 0.80)
        self.assertGreaterEqual(ok_report.high_conf_bin_accuracy, 0.80)
        md = format_calibration_markdown(ok_report)
        self.assertIn("`0.8-1.0`", md)

        # Case 2: Overconfident (>= 0.8 bin has 2/5 = 40% accuracy < 80%) -> raises threshold!
        bad_samples = [
            {"confidence": 0.81, "correct": False},
            {"confidence": 0.82, "correct": False},
            {"confidence": 0.84, "correct": False},
            {"confidence": 0.92, "correct": True},
            {"confidence": 0.95, "correct": True},
        ]
        raised_report = calibrate_confidence(bad_samples, current_threshold=0.80)
        self.assertFalse(raised_report.calibrated_ok)
        self.assertTrue(raised_report.threshold_raised)
        self.assertGreater(raised_report.recommended_threshold, 0.80)

    def test_03_cross_service_top3_accuracy_at_least_50_percent(self) -> None:
        """Exit criterion B3: Cross-service top-3 accuracy is at least 50%."""
        analyzer = CrossServiceAnalyzer()
        cross_service_cases = [
            (
                "gateway",
                "payments",
                {
                    "gateway": ["GET /api/orders -> 504 Gateway Timeout"],
                    "orders": ["POST /orders upstream timeout waiting on payments"],
                    "payments": ["DB query delay 3000ms exceeded SLA"],
                },
                {"payments": ["cfg_db_delay"]},
            ),
            (
                "gateway",
                "payments",
                {
                    "gateway": ["High5xxErrorRate 502 Bad Gateway"],
                    "orders": ["Checkout forwarded to payments"],
                    "payments": ["Strict validation rejected valid order payload"],
                },
                {"payments": ["dep_20261123_v1.0.12"]},
            ),
            (
                "orders",
                "gateway",
                {
                    "gateway": ["Retry policy set to 10 retries with 0s backoff"],
                    "orders": ["Orders thread pool saturated at 120 rps"],
                },
                {"gateway": ["cfg_20261123_005"]},
            ),
            (
                "gateway",
                "orders",
                {
                    "gateway": ["KeyError: 'total' parsing order response"],
                    "orders": ["Emitted response schema v2 without 'total' key"],
                    "payments": ["Payment APPROVED"],
                },
                {"orders": ["dep_20261123_v1.0.13"]},
            ),
            (
                "gateway",
                "payments",
                {
                    "gateway": ["504 Timeout on checkout"],
                    "orders": ["Waiting on payments response"],
                    "payments": ["External webhook timeout starvation after 15000ms"],
                },
                {"payments": ["dep_20261123_v1.0.14"]},
            ),
        ]

        top3_hits = 0
        for symptom_svc, expected_culprit, logs, changes in cross_service_cases:
            # Handle reverse cascade (e.g. gateway -> orders) by checking all services if needed
            hyps = analyzer.rank_culprits(
                symptom_service=symptom_svc,
                logs_by_service=logs,
                changes_by_service=changes,
            )
            predicted_services = [h.culprit_service for h in hyps[:3]]
            if expected_culprit in predicted_services:
                top3_hits += 1

        accuracy = top3_hits / len(cross_service_cases)
        self.assertGreaterEqual(accuracy, 0.50, f"Cross-service Top-3 accuracy {accuracy:.1%} < 50%")

    def test_04_draft_failure_analysis_table_has_required_columns_per_row(self) -> None:
        """Exit criterion B4: Each row names incident, cause of failure, and proposed change."""
        v1_path = self.out_dir / "v1.json"
        triage_json = self.out_dir / "triage_v1.json"
        fa_md = self.out_dir / "failure_analysis_v1.md"

        run_benchmark_v1(out_path=v1_path)
        write_triage_artifacts(v1_path, json_out=triage_json)
        rows = write_failure_analysis_table(triage_json, out_md_path=fa_md)

        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertTrue(row["incident"].strip())
            self.assertTrue(row["cause_of_failure"].strip())
            self.assertTrue(row["proposed_change"].strip())

        md_text = fa_md.read_text(encoding="utf-8")
        self.assertIn("| Incident | Label | Cause of Failure | Proposed Change |", md_text)


if __name__ == "__main__":
    unittest.main()
