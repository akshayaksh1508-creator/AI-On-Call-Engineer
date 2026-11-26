import unittest

from fastapi.testclient import TestClient

from dashboard.app import create_dashboard_app


class TestWebControls(unittest.TestCase):
    def setUp(self):
        self.app = create_dashboard_app()
        self.client = TestClient(self.app)

    def test_faults_list_and_trigger_fault_001(self):
        resp = self.client.get("/api/control/faults")
        self.assertEqual(resp.status_code, 200)
        faults = resp.json()["faults"]
        self.assertGreaterEqual(len(faults), 3)

        trig = self.client.post("/api/control/trigger", json={"fault_id": "fault_001_bad_deploy"})
        self.assertEqual(trig.status_code, 200)
        self.assertEqual(trig.json()["verdict"], "PASS")

        st = self.client.get("/api/state").json()
        self.assertEqual(st["verdict"], "PASS")
        self.assertGreaterEqual(len(st["trace"]), 3)
        self.assertGreaterEqual(len(st["evidence_ids"]), 3)

    def test_curveball_triggers_safe_escalation(self):
        trig = self.client.post(
            "/api/control/trigger",
            json={"fault_id": "fault_016_slow_query_missing_index"},
        )
        self.assertEqual(trig.status_code, 200)
        self.assertEqual(trig.json()["verdict"], "SAFE_ESCALATION")

    def test_kill_switch_blocks_autonomous_remediation(self):
        ks = self.client.post("/api/control/kill-switch", json={"armed": True})
        self.assertEqual(ks.status_code, 200)
        self.assertTrue(ks.json()["kill_switch_armed"])

        trig = self.client.post("/api/control/trigger", json={"fault_id": "fault_001_bad_deploy"})
        self.assertEqual(trig.status_code, 200)
        self.assertTrue(trig.json()["kill_switch_blocked"])
        self.assertEqual(trig.json()["verdict"], "ESCALATED (KILL SWITCH)")

    def test_offline_replay_and_reset(self):
        rep = self.client.post("/api/control/offline-replay")
        self.assertEqual(rep.status_code, 200)
        self.assertIn("OFFLINE REPLAY", rep.json()["verdict"])

        rst = self.client.post("/api/control/reset")
        self.assertEqual(rst.status_code, 200)
        self.assertEqual(rst.json()["state"]["timeline"], [])

    def test_in_app_final_results_and_backup_video_routes(self):
        r1 = self.client.get("/final-results")
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.get("/backup-video")
        self.assertEqual(r2.status_code, 200)


if __name__ == "__main__":
    unittest.main()
