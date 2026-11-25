"""Unit tests for 5-Chart Results Page (A3) & Live Dashboard / Trace View (B1, B2).

Verifies:
1. Task A3: One-command chart generation creates all 5 SVG charts matching JSON values.
2. Task B1: Live dashboard displays timeline, agent trace, evidence, metric graph with
   fault/fix markers, verdict, and cost; pushed events appear within 2 seconds.
3. Task B2: Tool calls are collapsible and evidence IDs resolve to the exact raw log line.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from bench.charts import generate_all_five_charts
from dashboard import DashboardState, create_dashboard_app


class TestDashboardAndCharts(unittest.TestCase):
    """Test suite for Day 9 Tasks A3, B1, and B2."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_five_charts_and_results_page_match_json_values(self) -> None:
        """Exit criterion A3 & Day 9 Gate: 5 charts regenerated and match JSON values."""
        repo_root = Path(__file__).resolve().parents[2]
        v2_path = repo_root / "results" / "v2_improved.json"
        hb_path = repo_root / "results" / "human_baseline.json"
        abl_path = repo_root / "results" / "ablations" / "ablation_summary.json"

        res = generate_all_five_charts(
            results_path=v2_path,
            human_baseline_path=hb_path,
            ablation_summary_path=abl_path,
            out_dir=self.out_dir / "charts",
            html_out=self.out_dir / "results_page.html",
        )

        self.assertEqual(len(res["charts"]), 5)
        for key, path_str in res["charts"].items():
            p = Path(path_str)
            self.assertTrue(p.exists(), f"Missing chart {key}")
            self.assertIn("<svg", p.read_text(encoding="utf-8"))

        # Verify chart values match source JSON
        v2_json = json.loads(v2_path.read_text(encoding="utf-8"))
        hb_json = json.loads(hb_path.read_text(encoding="utf-8"))
        self.assertAlmostEqual(res["values"]["agent_mean_time"], v2_json["summary"]["mean_total_time"])
        self.assertAlmostEqual(res["values"]["human_mean_time"], hb_json["summary"]["mean_duration_seconds"])
        self.assertTrue(Path(res["results_page"]).exists())

    def test_02_live_dashboard_events_within_2s_and_clickable_evidence(self) -> None:
        """Exit criteria B1 & B2: Events appear < 2s, collapsible trace, clickable evidence ID."""
        # Populate results page in temp dir for /results endpoint
        (self.out_dir / "results_page.html").write_text("<h1>5 Charts</h1>", encoding="utf-8")
        state = DashboardState()
        app = create_dashboard_app(state=state, results_dir=self.out_dir)
        client = TestClient(app)

        # 1. Verify HTML has 1080p readable structure, collapsible trace, and clickable evidence JS
        home = client.get("/")
        self.assertEqual(home.status_code, 200)
        html = home.text
        self.assertIn("Incident Timeline", html)
        self.assertIn("Metric Graph", html)
        self.assertIn("details class=\"tool-call\"", html)
        self.assertIn("evidence-btn", html)

        # 2. Push live events and confirm < 2s appearance in /api/state
        t0 = time.monotonic()
        r1 = client.post(
            "/api/events",
            json={
                "incident_id": "inc_live_901",
                "stage": "Detected",
                "message": "HTTP 500 spike detected on orders",
                "metric_error_rate": 0.22,
                "marker": "fault",
            },
        )
        self.assertEqual(r1.status_code, 200)

        r2 = client.post(
            "/api/events",
            json={
                "incident_id": "inc_live_901",
                "stage": "Investigating",
                "message": "Called query_logs on orders",
                "tool_name": "query_logs",
                "tool_args": {"service": "orders", "level": "ERROR"},
                "tool_output": "TypeError: 'NoneType' object is not subscriptable",
                "evidence_id": "ev_log_901",
                "raw_log": "2026-11-25T18:45:00Z ERROR orders/app.py:82 TypeError: 'NoneType' object is not subscriptable",
            },
        )
        self.assertEqual(r2.status_code, 200)

        r3 = client.post(
            "/api/events",
            json={
                "incident_id": "inc_live_901",
                "stage": "Resolved",
                "message": "Canary & production metrics recovered",
                "metric_error_rate": 0.002,
                "marker": "fix",
                "verdict": "PASS",
                "cost_usd": 0.014,
            },
        )
        self.assertEqual(r3.status_code, 200)

        st_resp = client.get("/api/state")
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 2.0, "Events must appear on dashboard within 2 seconds")
        self.assertEqual(st_resp.status_code, 200)

        st = st_resp.json()
        self.assertEqual(st["verdict"], "PASS")
        self.assertAlmostEqual(st["cost_usd"], 0.014)
        self.assertEqual(len(st["timeline"]), 3)
        self.assertEqual(len(st["trace"]), 1)
        self.assertEqual(len(st["metric_series"]), 2)
        self.assertEqual(st["metric_series"][0]["marker"], "fault")
        self.assertEqual(st["metric_series"][1]["marker"], "fix")

        # 3. Click evidence ID -> opens exact raw log line
        ev_resp = client.get("/api/evidence/ev_log_901")
        self.assertEqual(ev_resp.status_code, 200)
        self.assertIn("orders/app.py:82 TypeError", ev_resp.json()["raw_log"])

        # 4. /results page serves cleanly
        res_page = client.get("/results")
        self.assertEqual(res_page.status_code, 200)


if __name__ == "__main__":
    unittest.main()
