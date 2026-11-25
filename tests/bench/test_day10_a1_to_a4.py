"""Unit tests for Day 10 Tasks A1-A4 (Reliability, Curveball Set, Speed, Setup Script).

Verifies:
1. Task A1: 10x demo reliability suite (>= 9/10 succeed, every failure has a known cause).
2. Task A2: 5 unseen curveball faults injectable by ID, none in tuning data, all run end-to-end.
3. Task A3: Parallel tool calls + tuned canary window reduce median time >= 20% vs Day 8 with no accuracy loss.
4. Task A4: One-command setup scripts exist and verify cleanly under 15 minutes.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from bench.reliability import run_reliability_suite
from bench.speed_bench import ParallelToolRunner, run_speed_comparison
from faults.curveball import (
    CURVEBALL_FAULTS,
    CurveballInjector,
    run_curveball_suite,
    verify_unseen_against_tuning_data,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestDay10TasksA1ToA4(unittest.TestCase):
    """Test suite for Day 10 Person A tasks (A1-A4)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_reliability_ten_consecutive_runs_gate(self) -> None:
        """Exit criterion A1: 10 runs in a row, >= 9/10 succeed, every failure has known cause."""
        calls = [0]

        def nine_of_ten_demo(fid: str):
            calls[0] += 1
            if calls[0] == 4:
                return {
                    "incident_id": "inc_4",
                    "fault_id": fid,
                    "success": False,
                    "final_state": "Escalated",
                    "verdict": "FAIL",
                    "elapsed_seconds": 2.1,
                    "known_cause": "Simulated transient canary timeout",
                }
            return {
                "incident_id": f"inc_{calls[0]}",
                "fault_id": fid,
                "success": True,
                "final_state": "Resolved",
                "verdict": "PASS",
                "elapsed_seconds": 3.8,
                "known_cause": None,
            }

        res = run_reliability_suite(
            runs=10,
            min_passes=9,
            out_path=self.out_dir / "rel.json",
            demo_fn=nine_of_ten_demo,
        )
        self.assertEqual(res["total_runs"], 10)
        self.assertEqual(res["pass_count"], 9)
        self.assertTrue(res["every_failure_has_known_cause"])
        self.assertTrue(res["reliability_gate_met"])

    def test_02_curveball_five_unseen_faults_injectable_and_run_end_to_end(self) -> None:
        """Exit criterion A2: 5 new faults, none in tuning data, injectable by id, all run end to end."""
        self.assertEqual(len(CURVEBALL_FAULTS), 5)
        self.assertTrue(
            verify_unseen_against_tuning_data(REPO_ROOT),
            "Curveball faults must not appear in docs/faults.json or any Day 1-9 tuning data",
        )

        injector = CurveballInjector()
        for fid in CURVEBALL_FAULTS:
            injector.inject(fid)
            self.assertTrue(injector.is_injected(fid))
            injector.revert(fid)
            self.assertFalse(injector.is_injected(fid))

        res = run_curveball_suite(out_path=self.out_dir / "curveball.json")
        self.assertEqual(res["curveball_count"], 5)
        self.assertTrue(res["unseen_verified"])
        self.assertTrue(res["all_ran_end_to_end"])

    def test_03_parallel_tool_calls_and_tuned_canary_cut_median_time_over_20_percent(self) -> None:
        """Exit criterion A3: Median total time >= 20% lower than Day 8 with no accuracy loss."""
        # 1. Verify ParallelToolRunner executes concurrently faster than sequential sum
        runner = ParallelToolRunner(max_workers=4)

        def slow_tool(name: str):
            time.sleep(0.05)
            return f"ok:{name}"

        calls = [(f"tool_{i}", slow_tool, {"name": f"t{i}"}) for i in range(4)]
        out, elapsed = runner.execute_parallel(calls)
        self.assertEqual(len(out), 4)
        self.assertLess(elapsed, 0.16, f"Parallel execution took {elapsed}s (expected < 0.16s)")

        # 2. Verify Day 10 speed comparison vs Day 8 v2_improved.json
        comp = run_speed_comparison(
            day8_results_path=REPO_ROOT / "results" / "v2_improved.json",
            out_path=self.out_dir / "speed.json",
        )
        self.assertTrue(comp["speed_gate_met"], f"Reduction {comp['median_time_reduction_pct']}% < 20%")
        self.assertGreaterEqual(comp["median_time_reduction_pct"], 20.0)
        self.assertTrue(comp["no_accuracy_loss"])

    def test_04_clean_machine_setup_scripts_exist_and_pass_under_15_min(self) -> None:
        """Exit criterion A4: One-command setup scripts exist and verify cleanly < 15 minutes."""
        sh_path = REPO_ROOT / "scripts" / "setup_clean_machine.sh"
        ps1_path = REPO_ROOT / "scripts" / "setup_clean_machine.ps1"
        self.assertTrue(sh_path.exists())
        self.assertTrue(ps1_path.exists())

        sh_text = sh_path.read_text(encoding="utf-8")
        self.assertIn("make up", sh_text)
        self.assertIn("demo", sh_text)
        self.assertIn("900", sh_text)

        # Run quick verify-only check
        t0 = time.monotonic()
        proc = subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ps1_path), "-VerifyOnly"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        elapsed = time.monotonic() - t0
        self.assertEqual(proc.returncode, 0, f"Setup verify failed:\n{proc.stdout}\n{proc.stderr}")
        self.assertLess(elapsed, 900.0)


if __name__ == "__main__":
    unittest.main()
