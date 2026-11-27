import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from dashboard.app import create_dashboard_app

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestWebControls(unittest.TestCase):
    def setUp(self):
        self.app = create_dashboard_app()
        self.client = TestClient(self.app)

    def test_initial_state_neutral_and_no_time_tabs(self):
        st = self.client.get("/api/state").json()
        self.assertEqual(st["verdict"], "None yet")
        self.assertEqual(st["detector_state"], "Idle")
        self.assertIsNone(st["revealed_ground_truth"])

        html = self.client.get("/").text
        self.assertNotIn("Last 1h", html)
        self.assertNotIn("Always On", html)

    def test_faults_list_neutral_and_trigger_fault_001_no_leak_and_increasing_times(self):
        resp = self.client.get("/api/control/faults")
        self.assertEqual(resp.status_code, 200)
        faults = resp.json()["faults"]
        self.assertGreaterEqual(len(faults), 3)
        for f in faults:
            self.assertIn("Scenario ", f["neutral_label"])
            self.assertNotIn("fault_0", f["neutral_label"])

        trig = self.client.post("/api/control/trigger", json={"fault_id": "fault_001_bad_deploy"})
        self.assertEqual(trig.status_code, 200)
        body = trig.json()
        self.assertEqual(body["verdict"], "Resolved")
        self.assertIn(
            body["execution_mode"],
            ("Heuristic Baseline", "Live LLM (Gemini)", "Live LLM (ChatGPT)", "Live LLM (Claude)"),
        )
        self.assertEqual(body["ground_truth"]["fault_id"], "fault_001_bad_deploy")

        st = self.client.get("/api/state").json()
        self.assertEqual(st["verdict"], "Resolved")
        self.assertEqual(st["detector_state"], "Idle")
        self.assertIsNotNone(st["revealed_ground_truth"])
        # 1. No fault name leak in incident_id, timeline, or evidence IDs
        self.assertNotIn("fault_0", st["incident_id"])
        for ev_id in st["evidence_ids"]:
            self.assertRegex(ev_id, r"^E\d+$")
        for item in st["timeline"]:
            self.assertNotIn("fault_0", item["message"])

        # 2. Strictly increasing timestamps and elapsed_s
        timestamps = [item["timestamp"] for item in st["timeline"]]
        elapsed = [item["elapsed_s"] for item in st["timeline"]]
        for i in range(1, len(timestamps)):
            self.assertGreater(timestamps[i], timestamps[i - 1])
            self.assertGreater(elapsed[i], elapsed[i - 1])

        # 3. Metric graph has t_sec and all 4 markers
        markers = [pt.get("marker") for pt in st["metric_series"] if pt.get("marker")]
        for required in ("Fault", "Detected", "Fix promoted", "Recovered"):
            self.assertIn(required, markers)

    def test_live_source_change_alters_diagnosis(self):
        buggy_path = REPO_ROOT / "faults" / "catalog" / "fault_001_bad_deploy" / "buggy_app.py"
        original = buggy_path.read_text(encoding="utf-8")
        try:
            modified = original.replace("def create_order(", "def create_order_judge_check(", 1)
            buggy_path.write_text(modified, encoding="utf-8")
            self.client.post("/api/control/trigger", json={"fault_id": "fault_001_bad_deploy"})
            st = self.client.get("/api/state").json()
            trace_text = " ".join(tr["tool_output"] for tr in st["trace"])
            self.assertIn("create_order_judge_check", trace_text)
        finally:
            buggy_path.write_text(original, encoding="utf-8")

    def test_curveball_random_held_out_and_specific_t3(self):
        rand_cb = self.client.post("/api/control/curveball", json={})
        self.assertEqual(rand_cb.status_code, 200)
        self.assertIn(rand_cb.json()["verdict"], ("Resolved", "Escalated", "Rolled back"))

        trig = self.client.post(
            "/api/control/curveball",
            json={"fault_id": "fault_016_slow_query_missing_index"},
        )
        self.assertEqual(trig.status_code, 200)
        self.assertEqual(trig.json()["verdict"], "Escalated")

    def test_kill_switch_blocks_autonomous_remediation(self):
        ks = self.client.post("/api/control/kill-switch", json={"armed": True})
        self.assertEqual(ks.status_code, 200)
        self.assertTrue(ks.json()["kill_switch_armed"])

        trig = self.client.post("/api/control/trigger", json={"fault_id": "fault_001_bad_deploy"})
        self.assertEqual(trig.status_code, 200)
        self.assertTrue(trig.json()["kill_switch_blocked"])
        self.assertEqual(trig.json()["verdict"], "Escalated (Kill Switch)")

    def test_offline_replay_and_reset(self):
        rep = self.client.post("/api/control/offline-replay")
        self.assertEqual(rep.status_code, 200)
        self.assertEqual(rep.json()["execution_mode"], "Replay")
        self.assertEqual(rep.json()["verdict"], "Resolved (Replay)")

        rst = self.client.post("/api/control/reset")
        self.assertEqual(rst.status_code, 200)
        self.assertEqual(rst.json()["state"]["timeline"], [])
        self.assertEqual(rst.json()["state"]["verdict"], "None yet")

    def test_in_app_final_results_and_backup_video_routes(self):
        r1 = self.client.get("/final-results")
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.get("/backup-video")
        self.assertEqual(r2.status_code, 200)

    def test_n8n_inbound_webhook_triggers_incident(self):
        resp = self.client.post("/api/webhooks/n8n", json={"fault_id": "fault_001_bad_deploy"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["verdict"], "Resolved")

    def test_gemini_live_mode_and_cost_tracking(self):
        import os
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Null discount dict dereference in create_order()."}]}}],
            "usageMetadata": {"promptTokenCount": 400, "candidatesTokenCount": 40, "totalTokenCount": 440},
        }
        with patch.dict(os.environ, {"GEMINI_API_KEY": "AIza-test-gemini-key"}, clear=False):
            with patch("httpx.post", return_value=mock_resp):
                resp = self.client.post("/api/control/trigger", json={"fault_id": "fault_001_bad_deploy"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["execution_mode"], "Live LLM (Gemini)")
        self.assertEqual(body["tokens"], 440)
        self.assertGreater(body["cost_usd"], 0.0)

    def test_openai_chatgpt_live_mode_and_cost_tracking(self):
        import os
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Null discount dict dereference in create_order()."}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 50, "total_tokens": 550},
        }
        def _fake_env(name, repo_root=REPO_ROOT):
            if name == "OPENAI_API_KEY":
                return "sk-test-chatgpt-key"
            return None

        with patch("dashboard.app._resolve_env_var", side_effect=_fake_env):
            with patch("httpx.post", return_value=mock_resp):
                resp = self.client.post("/api/control/trigger", json={"fault_id": "fault_001_bad_deploy"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["execution_mode"], "Live LLM (ChatGPT)")
        self.assertEqual(body["tokens"], 550)
        self.assertGreater(body["cost_usd"], 0.0)

    def test_settings_get_and_update(self):
        r1 = self.client.get("/api/settings")
        self.assertEqual(r1.status_code, 200)
        self.assertAlmostEqual(r1.json()["spend_cap_usd"], 50.0)

        r2 = self.client.post(
            "/api/settings",
            json={"spend_cap_usd": 75.0, "confidence_threshold_t1": 0.85},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertAlmostEqual(r2.json()["settings"]["spend_cap_usd"], 75.0)
        self.assertAlmostEqual(r2.json()["settings"]["confidence_threshold_t1"], 0.85)


if __name__ == "__main__":
    unittest.main()
