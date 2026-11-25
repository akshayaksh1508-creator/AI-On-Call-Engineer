"""Unit tests for BenchmarkRunner & Flake Handling (Day 7 Tasks A1 & A4).

Verifies:
1. Task A1: 20 faults run unattended with zero harness crashes.
2. Task A1: Environment is reset and confirmed healthy (30s window) between runs.
3. Task A1 Gate: Full benchmark run produces valid `results.json` with 20 RunRecords.
4. Task A4: Killing a service mid-run records `infra_error` (not `fail`) and retries once.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bench.flake_handler import ServiceKilledError
from bench.runner import BenchmarkRunner, load_fault_catalogue
from contracts.models import RunRecord


class FakeClock:
    """Deterministic monotonic clock + sleep pair for testing 30s health windows instantly."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, dt: float) -> None:
        self.now += dt


class TestBenchmarkRunnerAndFlakeHandling(unittest.TestCase):
    """Test suite for Day 7 Tasks A1 and A4."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)
        self.results_path = self.out_dir / "results.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_twenty_faults_run_unattended_with_healthy_resets_and_results_json(self) -> None:
        """Exit criterion A1: 20 faults run unattended with zero crashes and produce results.json."""
        fault_ids, cats = load_fault_catalogue(limit=20)
        self.assertEqual(len(fault_ids), 20)

        events: list[str] = []
        clock = FakeClock()

        def reset_fn(fid: str) -> None:
            events.append(f"reset:{fid}")

        def health_fn() -> bool:
            return True

        def inject_fn(fid: str) -> None:
            events.append(f"inject:{fid}")

        def orchestrate_fn(fid: str) -> RunRecord:
            events.append(f"orchestrate:{fid}")
            # Simulate 1 agent failure on fault 4 (must NOT crash the harness!)
            fix_ok = not fid.startswith("fault_004")
            return RunRecord(
                incident_id=f"inc_{fid}",
                fault_id=fid,
                t_detect=5.0,
                t_rca=2.0,
                t_fix=1.5,
                t_verified=3.5,
                rca_correct_top1=True,
                rca_correct_top3=True,
                fix_ok=fix_ok,
                unsafe=False,
                tokens=1200,
                cost_usd=0.012,
            )

        runner = BenchmarkRunner(
            reset_fn=reset_fn,
            health_fn=health_fn,
            inject_fn=inject_fn,
            orchestrate_fn=orchestrate_fn,
            confirm_healthy_seconds=30.0,
            health_poll_interval=5.0,
            sleep_fn=clock.sleep,
            clock_fn=clock.time,
        )

        payload = runner.run(fault_ids, out_path=self.results_path, category_by_fault=cats)

        # Gate: results.json exists and contains all 20 runs
        self.assertTrue(self.results_path.exists())
        loaded = json.loads(self.results_path.read_text(encoding="utf-8"))
        self.assertEqual(loaded["fault_count"], 20)
        self.assertEqual(len(loaded["runs"]), 20)
        self.assertEqual(len(loaded["records"]), 20)
        self.assertEqual(payload["summary"]["total_runs"], 20)
        self.assertEqual(payload["summary"]["fix_ok_count"], 19)

        # Every fault had pre-reset, inject, orchestrate, post-reset
        for fid in fault_ids:
            self.assertEqual(events.count(f"reset:{fid}"), 2)
            self.assertEqual(events.count(f"inject:{fid}"), 1)
            self.assertEqual(events.count(f"orchestrate:{fid}"), 1)

        # 30s health check ran for each of the 20 faults (>= 20 * 30s = 600s simulated)
        self.assertGreaterEqual(clock.now - 1000.0, 600.0)

    def test_02_kill_service_mid_run_records_infra_error_and_retries_once(self) -> None:
        """Exit criterion A4: Kill service mid-run -> record says infra_error (not fail) and retries once."""
        clock = FakeClock()
        service_alive = [True]
        attempt_counter = [0]

        def reset_fn(_fid: str) -> None:
            service_alive[0] = True

        def health_fn() -> bool:
            return service_alive[0]

        def orchestrate_killed_both_times(fid: str) -> RunRecord:
            attempt_counter[0] += 1
            # Simulate killing a service mid-run
            service_alive[0] = False
            raise ServiceKilledError(f"orders service killed (SIGKILL) during {fid}")

        runner = BenchmarkRunner(
            reset_fn=reset_fn,
            health_fn=health_fn,
            orchestrate_fn=orchestrate_killed_both_times,
            confirm_healthy_seconds=30.0,
            health_poll_interval=5.0,
            max_infra_retries=1,
            sleep_fn=clock.sleep,
            clock_fn=clock.time,
        )

        entry = runner.run_fault("fault_001_bad_deploy")
        self.assertEqual(attempt_counter[0], 2, "Must run initial attempt + 1 retry")
        self.assertEqual(entry.status, "infra_error")
        self.assertNotEqual(entry.status, "fail")
        self.assertTrue(entry.had_infra_error)
        self.assertTrue(entry.retried)
        self.assertEqual(entry.retry_count, 1)
        self.assertEqual([a["status"] for a in entry.attempts], ["infra_error", "infra_error"])

    def test_03_infra_error_recovers_on_single_retry(self) -> None:
        """If service is killed on attempt 1, retry once and succeed if attempt 2 passes."""
        clock = FakeClock()
        attempt_counter = [0]

        def orchestrate_flaky(fid: str) -> RunRecord:
            attempt_counter[0] += 1
            if attempt_counter[0] == 1:
                raise ConnectionRefusedError("Connection refused: payments service died mid-run")
            return RunRecord(
                incident_id=f"inc_{fid}_ok",
                fault_id=fid,
                t_detect=4.0,
                t_rca=1.0,
                t_fix=1.0,
                t_verified=2.0,
                rca_correct_top1=True,
                rca_correct_top3=True,
                fix_ok=True,
                unsafe=False,
            )

        runner = BenchmarkRunner(
            orchestrate_fn=orchestrate_flaky,
            confirm_healthy_seconds=1.0,
            health_poll_interval=0.5,
            max_infra_retries=1,
            sleep_fn=clock.sleep,
            clock_fn=clock.time,
        )

        entry = runner.run_fault("fault_017_symptom_gw_cause_payments")
        self.assertEqual(attempt_counter[0], 2)
        self.assertEqual(entry.initial_status, "infra_error")
        self.assertEqual(entry.status, "pass")
        self.assertTrue(entry.had_infra_error)
        self.assertTrue(entry.retried)
        self.assertEqual(entry.retry_count, 1)

    def test_04_agent_failure_not_retried_and_classified_as_fail(self) -> None:
        """Genuine agent/verification failure is classified as `fail`, not `infra_error`, and not retried."""
        clock = FakeClock()
        attempt_counter = [0]

        def orchestrate_agent_fail(fid: str) -> RunRecord:
            attempt_counter[0] += 1
            return RunRecord(
                incident_id=f"inc_{fid}_fail",
                fault_id=fid,
                t_detect=5.0,
                t_rca=3.0,
                t_fix=2.0,
                t_verified=4.0,
                rca_correct_top1=False,
                rca_correct_top3=False,
                fix_ok=False,
                unsafe=False,
            )

        runner = BenchmarkRunner(
            orchestrate_fn=orchestrate_agent_fail,
            confirm_healthy_seconds=1.0,
            health_poll_interval=0.5,
            max_infra_retries=1,
            sleep_fn=clock.sleep,
            clock_fn=clock.time,
        )

        entry = runner.run_fault("fault_002_off_by_one")
        self.assertEqual(attempt_counter[0], 1)
        self.assertEqual(entry.status, "fail")
        self.assertFalse(entry.had_infra_error)
        self.assertFalse(entry.retried)
        self.assertEqual(entry.retry_count, 0)


if __name__ == "__main__":
    unittest.main()
