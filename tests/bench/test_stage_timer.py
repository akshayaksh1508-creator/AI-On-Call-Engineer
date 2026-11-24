"""Unit tests for Stage Timing and RunRecord Generation (Day 6 Task A3).

Verifies:
1. Stage timestamps (t_detect, t_rca, t_fix, t_verified) are strictly increasing across 3 runs.
2. Total run duration matches an independent stopwatch within 5 seconds across 3 runs.
3. Output strictly validates against contracts.models.RunRecord schema.
4. Stage durations correctly sum to total elapsed time.
5. Missing stage timestamps are safely caught and reported.
6. Persistence to JSON and JSONL.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure repo root is on path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bench.stage_timer import StageTimeline, StageTimer
from contracts.models import RunRecord


class TestStageTimer(unittest.TestCase):
    """Test suite for Day 6 Task A3 Stage Timing and RunRecord."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.results_dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_01_three_runs_timestamps_strictly_increasing(self):
        """Exit criterion: In 3 runs the timestamps are strictly increasing."""
        runs_data = []

        for run_idx in range(1, 4):
            timer = StageTimer(
                incident_id=f"inc_20261124_00{run_idx}",
                fault_id=f"fault_00{run_idx}_test",
            )

            # Record stages with small real delays to ensure strictly increasing clock
            t_inj = timer.record_inject()
            time.sleep(0.01)

            t_det = timer.record_detect()
            time.sleep(0.01)

            t_rca = timer.record_rca(correct_top1=True, correct_top3=True)
            time.sleep(0.01)

            t_fix = timer.record_fix()
            time.sleep(0.01)

            t_ver = timer.record_verified(fix_ok=True)

            timeline = timer.get_timeline()
            runs_data.append((run_idx, timeline))

            # 1. Monotonicity verification
            self.assertTrue(
                timeline.is_strictly_increasing,
                f"Run {run_idx} timestamps must be strictly increasing: {timeline}",
            )
            self.assertLess(timeline.t_inject, timeline.t_detect)
            self.assertLess(timeline.t_detect, timeline.t_rca)
            self.assertLess(timeline.t_rca, timeline.t_fix)
            self.assertLess(timeline.t_fix, timeline.t_verified)

            # 2. Positive stage durations
            durations = timeline.stage_durations
            self.assertGreater(durations["t_detect"], 0.0)
            self.assertGreater(durations["t_rca"], 0.0)
            self.assertGreater(durations["t_fix"], 0.0)
            self.assertGreater(durations["t_verified"], 0.0)

        self.assertEqual(len(runs_data), 3, "Must evaluate exactly 3 runs")

    def test_02_three_runs_total_time_matches_stopwatch_within_5s(self):
        """Exit criterion: In 3 runs total time matches a stopwatch within 5 s."""
        for run_idx in range(1, 4):
            # External stopwatch measuring the run independently
            stopwatch_start = time.perf_counter()

            timer = StageTimer(
                incident_id=f"inc_stopwatch_00{run_idx}",
                fault_id=f"fault_00{run_idx}",
            )

            # Simulate lifecycle stages with realistic stage delays
            timer.record_inject()
            time.sleep(0.03)

            timer.record_detect()
            time.sleep(0.02)

            timer.record_rca()
            time.sleep(0.02)

            timer.record_fix()
            time.sleep(0.02)

            timer.record_verified()
            stopwatch_end = time.perf_counter()
            stopwatch_elapsed = stopwatch_end - stopwatch_start

            timeline = timer.get_timeline()
            record = timer.to_run_record()

            # Sum of stage times in RunRecord
            total_stage_time = record.t_detect + record.t_rca + record.t_fix + record.t_verified

            # Criterion: total time matches stopwatch within 5.0 seconds
            delta_timeline = abs(timeline.total_duration - stopwatch_elapsed)
            delta_record = abs(total_stage_time - stopwatch_elapsed)

            self.assertLessEqual(
                delta_timeline,
                5.0,
                f"Run {run_idx}: timeline duration {timeline.total_duration:.4f}s differed from stopwatch {stopwatch_elapsed:.4f}s by > 5s",
            )
            self.assertLessEqual(
                delta_record,
                5.0,
                f"Run {run_idx}: RunRecord total {total_stage_time:.4f}s differed from stopwatch {stopwatch_elapsed:.4f}s by > 5s",
            )
            self.assertTrue(timeline.matches_stopwatch(stopwatch_elapsed, tolerance=5.0))

    def test_03_run_record_schema_validation(self):
        """Output strictly conforms to contracts.models.RunRecord schema."""
        timer = StageTimer(
            incident_id="inc_schema_test",
            fault_id="fault_001_bad_deploy",
        )
        timer.record_inject(100.0)
        timer.record_detect(t=105.5)     # t_detect = 5.5s
        timer.record_rca(t=120.0)        # t_rca = 14.5s
        timer.record_fix(t=135.25)       # t_fix = 15.25s
        timer.record_verified(t=150.75)  # t_verified = 15.5s

        record = timer.to_run_record(tokens=1250, cost_usd=0.01875)

        # Validate schema type and fields
        self.assertIsInstance(record, RunRecord)
        self.assertEqual(record.incident_id, "inc_schema_test")
        self.assertEqual(record.fault_id, "fault_001_bad_deploy")
        self.assertEqual(record.t_detect, 5.5)
        self.assertEqual(record.t_rca, 14.5)
        self.assertEqual(record.t_fix, 15.25)
        self.assertEqual(record.t_verified, 15.5)
        self.assertTrue(record.rca_correct_top1)
        self.assertTrue(record.rca_correct_top3)
        self.assertTrue(record.fix_ok)
        self.assertFalse(record.unsafe)
        self.assertEqual(record.tokens, 1250)
        self.assertEqual(record.cost_usd, 0.01875)

        # Sum of stages
        total = record.t_detect + record.t_rca + record.t_fix + record.t_verified
        self.assertEqual(total, 50.75)

    def test_04_missing_timestamps_raise_value_error(self):
        """Incomplete runs with missing stages fail fast with a descriptive ValueError."""
        timer = StageTimer(incident_id="inc_partial", fault_id="fault_001")
        timer.record_inject(10.0)
        timer.record_detect(t=15.0)
        # Skipped RCA, Fix, Verified

        with self.assertRaises(ValueError) as ctx:
            timer.get_timeline()
        self.assertIn("missing stage timestamps", str(ctx.exception))
        self.assertIn("rca", str(ctx.exception))
        self.assertIn("fix", str(ctx.exception))
        self.assertIn("verified", str(ctx.exception))

    def test_05_persistence_to_json_and_jsonl(self):
        """RunRecord and timeline serialize cleanly to JSON and JSONL files."""
        timer = StageTimer(incident_id="inc_persist_01", fault_id="fault_002")
        timer.record_inject(200.0)
        timer.record_detect(t=210.0)
        timer.record_rca(t=225.0)
        timer.record_fix(t=240.0)
        timer.record_verified(t=260.0)

        # 1. JSON Array
        json_path = self.results_dir / "runs.json"
        timer.save(json_path)

        self.assertTrue(json_path.exists())
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["incident_id"], "inc_persist_01")
        self.assertIn("timestamps", data[0])
        self.assertEqual(data[0]["t_detect"], 10.0)

        # Append second run to same JSON array
        timer2 = StageTimer(incident_id="inc_persist_02", fault_id="fault_003")
        timer2.record_inject(300.0)
        timer2.record_detect(t=305.0)
        timer2.record_rca(t=315.0)
        timer2.record_fix(t=325.0)
        timer2.record_verified(t=340.0)
        timer2.save(json_path)

        data2 = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data2), 2)
        self.assertEqual(data2[1]["incident_id"], "inc_persist_02")

        # 2. JSONL
        jsonl_path = self.results_dir / "runs.jsonl"
        timer.save(jsonl_path)
        timer2.save(jsonl_path)

        lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["incident_id"], "inc_persist_01")
        self.assertEqual(json.loads(lines[1])["incident_id"], "inc_persist_02")


if __name__ == "__main__":
    unittest.main()
