"""Unit tests for Results Aggregator and Charts (Day 7 Task A3).

Verifies:
1. Metrics computed on synthetic RunRecords equal exact hand-calculated values.
2. Category grouping and infra error rate calculations are accurate.
3. SVG chart files (accuracy_chart.svg, time_chart.svg, cost_chart.svg) are generated cleanly.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bench.aggregator import aggregate_results, generate_charts
from contracts.models import RunRecord


class TestResultsAggregator(unittest.TestCase):
    """Test suite for Day 7 Task A3 Results Aggregator and Charts."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.chart_dir = Path(self.tmp.name) / "charts"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_synthetic_run_records_equal_hand_calculated_values(self) -> None:
        """Exit criterion A3: Metrics computed on synthetic RunRecords equal hand-calculated values."""
        records = [
            # Run 1: total = 10.0s, top1=T, top3=T, fix=T, unsafe=F, tokens=1000, cost=0.010
            RunRecord(
                incident_id="inc_1",
                fault_id="fault_001_bad_deploy",
                t_detect=2.0,
                t_rca=3.0,
                t_fix=1.0,
                t_verified=4.0,
                rca_correct_top1=True,
                rca_correct_top3=True,
                fix_ok=True,
                unsafe=False,
                tokens=1000,
                cost_usd=0.010,
            ),
            # Run 2: total = 20.0s, top1=F, top3=T, fix=T, unsafe=F, tokens=2000, cost=0.020
            RunRecord(
                incident_id="inc_2",
                fault_id="fault_002_off_by_one",
                t_detect=4.0,
                t_rca=6.0,
                t_fix=2.0,
                t_verified=8.0,
                rca_correct_top1=False,
                rca_correct_top3=True,
                fix_ok=True,
                unsafe=False,
                tokens=2000,
                cost_usd=0.020,
            ),
            # Run 3: total = 30.0s, top1=F, top3=F, fix=F, unsafe=T, tokens=3000, cost=0.030
            RunRecord(
                incident_id="inc_3",
                fault_id="fault_015_disk_full",
                t_detect=6.0,
                t_rca=9.0,
                t_fix=3.0,
                t_verified=12.0,
                rca_correct_top1=False,
                rca_correct_top3=False,
                fix_ok=False,
                unsafe=True,
                tokens=3000,
                cost_usd=0.030,
            ),
            # Run 4: total = 40.0s, top1=T, top3=T, fix=F, unsafe=F, tokens=4000, cost=0.040
            RunRecord(
                incident_id="inc_4",
                fault_id="fault_017_symptom_gw_cause_payments",
                t_detect=8.0,
                t_rca=12.0,
                t_fix=4.0,
                t_verified=16.0,
                rca_correct_top1=True,
                rca_correct_top3=True,
                fix_ok=False,
                unsafe=False,
                tokens=4000,
                cost_usd=0.040,
            ),
        ]
        cats = {
            "fault_001_bad_deploy": "code",
            "fault_002_off_by_one": "code",
            "fault_015_disk_full": "resource",
            "fault_017_symptom_gw_cause_payments": "cross_service",
        }
        run_entries = [
            {"fault_id": "fault_001_bad_deploy", "status": "pass"},
            {"fault_id": "fault_002_off_by_one", "status": "pass"},
            {"fault_id": "fault_015_disk_full", "status": "fail"},
            {"fault_id": "fault_017_symptom_gw_cause_payments", "status": "infra_error"},
        ]

        summary = aggregate_results(records, run_entries=run_entries, category_by_fault=cats)

        # Hand-calculated exact values:
        # N = 4
        # top1 = 2/4 = 0.50; top3 = 3/4 = 0.75; fix = 2/4 = 0.50; unsafe = 1/4 = 0.25; infra = 1/4 = 0.25
        self.assertEqual(summary["total_runs"], 4)
        self.assertAlmostEqual(summary["rca_top1_accuracy"], 0.5)
        self.assertAlmostEqual(summary["rca_top3_accuracy"], 0.75)
        self.assertAlmostEqual(summary["fix_success_rate"], 0.5)
        self.assertAlmostEqual(summary["unsafe_rate"], 0.25)
        self.assertEqual(summary["infra_error_count"], 1)
        self.assertAlmostEqual(summary["infra_error_rate"], 0.25)

        # Mean stage times:
        # t_detect: (2+4+6+8)/4 = 5.0
        # t_rca: (3+6+9+12)/4 = 7.5
        # t_fix: (1+2+3+4)/4 = 2.5
        # t_verified: (4+8+12+16)/4 = 10.0
        # total_times = [10, 20, 30, 40] -> mean = 25.0, median = 25.0, p95 = 10 + 0.95*30 = 38.5
        self.assertAlmostEqual(summary["mean_t_detect"], 5.0)
        self.assertAlmostEqual(summary["mean_t_rca"], 7.5)
        self.assertAlmostEqual(summary["mean_t_fix"], 2.5)
        self.assertAlmostEqual(summary["mean_t_verified"], 10.0)
        self.assertAlmostEqual(summary["mean_total_time"], 25.0)
        self.assertAlmostEqual(summary["median_total_time"], 25.0)
        self.assertAlmostEqual(summary["p95_total_time"], 38.5)

        # Tokens & cost:
        # tokens = 1000+2000+3000+4000 = 10000 -> mean = 2500.0
        # cost = 0.01+0.02+0.03+0.04 = 0.10 -> mean = 0.025
        self.assertEqual(summary["total_tokens"], 10000)
        self.assertAlmostEqual(summary["mean_tokens"], 2500.0)
        self.assertAlmostEqual(summary["total_cost_usd"], 0.10)
        self.assertAlmostEqual(summary["mean_cost_usd"], 0.025)

        # Category breakdown for "code" (N=2):
        self.assertEqual(summary["by_category"]["code"]["count"], 2)
        self.assertAlmostEqual(summary["by_category"]["code"]["rca_top1_accuracy"], 0.5)
        self.assertAlmostEqual(summary["by_category"]["code"]["fix_success_rate"], 1.0)
        self.assertAlmostEqual(summary["by_category"]["code"]["mean_total_time"], 15.0)

    def test_02_generate_svg_charts(self) -> None:
        """generate_charts writes valid non-empty SVG files for accuracy, time, and cost."""
        records = [
            RunRecord(
                incident_id="inc_1",
                fault_id="fault_001_bad_deploy",
                t_detect=5.0,
                t_rca=2.0,
                t_fix=1.0,
                t_verified=4.0,
                rca_correct_top1=True,
                rca_correct_top3=True,
                fix_ok=True,
                tokens=1500,
                cost_usd=0.015,
            )
        ]
        summary = aggregate_results(records)
        charts = generate_charts(summary, records, self.chart_dir)

        for key in ("accuracy_chart", "time_chart", "cost_chart"):
            path = Path(charts[key])
            self.assertTrue(path.exists(), f"Missing {key}")
            svg_text = path.read_text(encoding="utf-8")
            self.assertIn("<svg", svg_text)
            self.assertIn("</svg>", svg_text)


if __name__ == "__main__":
    unittest.main()
