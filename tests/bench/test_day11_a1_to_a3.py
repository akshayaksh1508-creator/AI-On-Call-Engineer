"""Unit tests for Day 11 Tasks A1-A3 (Final Benchmark, Final Exports, Offline Replay).

Verifies:
1. Task A1: Final benchmark runs all 20 faults (15 training + 5 held-out), writes final.json,
   and re-runs every failed fault once to label it `flaky` or `real`.
2. Task A2: Final 5 charts and failure table match every number in final.json.
3. Task A3: Offline replay plays a recorded run start-to-finish through the live dashboard
   even with external network calls blocked.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from bench.final_bench import export_final_charts_and_failure_table, run_final_benchmark
from bench.offline_replay import replay_recorded_run, save_recorded_replay
from contracts.models import RunRecord
from dashboard import DashboardState, create_dashboard_app

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestDay11TasksA1ToA3(unittest.TestCase):
    """Test suite for Day 11 Person A tasks (A1-A3)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_final_benchmark_all_20_faults_and_flaky_vs_real_labelling(self) -> None:
        """Exit criterion A1: All 20 faults (15 train + 5 held-out) run; failures re-run & labelled."""
        final_path = self.out_dir / "final.json"
        payload = run_final_benchmark(repo_root=REPO_ROOT, out_path=final_path)

        self.assertTrue(final_path.exists())
        self.assertEqual(payload["total_faults"], 20)
        self.assertEqual(payload["training_count"], 15)
        self.assertEqual(payload["held_out_count"], 5)
        self.assertEqual(len(payload["runs"]), 20)

        for r in payload["runs"]:
            if r["status"] != "pass" or not r["run_record"]["fix_ok"]:
                self.assertTrue(r["rerun_checked"], f"Failed run {r['fault_id']} was not re-run")
                self.assertIn(r["failure_classification"], ("flaky", "real"))

        # Synthetic check: a fault that fails once and passes on re-run is labelled 'flaky'
        attempts = [0]

        def flaky_once(fid: str):
            attempts[0] += 1
            ok = not (fid == "fault_001_bad_deploy" and attempts[0] == 1)
            return {
                "run_record": RunRecord(
                    incident_id=f"inc_{fid}_{attempts[0]}",
                    fault_id=fid,
                    t_detect=3.0,
                    t_rca=1.0,
                    t_fix=0.5,
                    t_verified=2.0,
                    rca_correct_top1=True,
                    rca_correct_top3=True,
                    fix_ok=ok,
                ),
                "success": ok,
                "error_message": None if ok else "Transient flake",
            }

        syn = run_final_benchmark(
            repo_root=REPO_ROOT,
            out_path=self.out_dir / "final_syn.json",
            orchestrate_fn=flaky_once,
        )
        first = syn["runs"][0]
        self.assertTrue(first["rerun_checked"])
        self.assertEqual(first["failure_classification"], "flaky")

    def test_02_final_charts_and_failure_table_match_final_json(self) -> None:
        """Exit criterion A2: Every number in exported charts & failure table matches final.json."""
        final_path = self.out_dir / "final.json"
        final_data = run_final_benchmark(repo_root=REPO_ROOT, out_path=final_path)

        exports = export_final_charts_and_failure_table(
            final_json_path=final_path,
            charts_dir=self.out_dir / "final_charts",
            html_out=self.out_dir / "final_results_page.html",
            failure_table_md=self.out_dir / "final_failure_table.md",
            failure_table_json=self.out_dir / "final_failure_table.json",
            repo_root=REPO_ROOT,
        )

        self.assertEqual(len(exports["charts"]), 5)
        for chart_file in exports["charts"].values():
            self.assertTrue(Path(chart_file).exists())
            self.assertIn("<svg", Path(chart_file).read_text(encoding="utf-8"))

        # Verify numbers match final.json
        self.assertAlmostEqual(
            exports["chart_values"]["agent_mean_time"],
            final_data["summary"]["mean_total_time"],
        )
        ft_json = json.loads(Path(exports["failure_table_json"]).read_text(encoding="utf-8"))
        self.assertEqual(ft_json["total_runs"], final_data["summary"]["total_runs"])
        self.assertEqual(ft_json["fix_ok_count"], final_data["summary"]["fix_ok_count"])
        expected_failures = sum(1 for r in final_data["runs"] if not r["run_record"]["fix_ok"])
        self.assertEqual(ft_json["total_failures"], expected_failures)

    def test_03_offline_replay_plays_start_to_finish_with_network_disconnected(self) -> None:
        """Exit criterion A3: Disconnected network still replays recorded run start to finish."""
        replay_file = save_recorded_replay(out_path=self.out_dir / "recorded_replay.json")
        state = DashboardState()
        app = create_dashboard_app(state=state, results_dir=self.out_dir)
        client = TestClient(app)

        # Simulate disconnected external network
        with patch("urllib.request.urlopen", side_effect=OSError("Network is unreachable")):
            result = replay_recorded_run(
                replay_path=replay_file,
                post_fn=lambda ev: client.post("/api/events", json=ev),
            )

        self.assertTrue(result["completed_start_to_finish"])
        self.assertEqual(result["started_at_stage"], "Detected")
        self.assertEqual(result["ended_at_stage"], "Resolved")
        self.assertEqual(result["events_replayed"], 6)

        st = client.get("/api/state").json()
        self.assertEqual(st["verdict"], "PASS")
        self.assertEqual(len(st["timeline"]), 6)
        self.assertEqual(len(st["trace"]), 3)
        ev_resp = client.get("/api/evidence/ev_replay_log_001")
        self.assertEqual(ev_resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
