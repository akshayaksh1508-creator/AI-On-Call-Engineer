import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import tempfile, unittest
from pathlib import Path

import yaml

from deployer.changes import ChangeLog
from deployer.runners import NoopRunner
from faults.env_faults import EnvFaultInjector, load_specs

SPECS = Path(__file__).resolve().parents[2] / "faults" / "specs"


class EnvFaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.runner = NoopRunner()
        self.log = ChangeLog(d / "changes.jsonl")
        self.inj = EnvFaultInjector(SPECS, self.runner, "docker-compose.yml", d / "override.yml", d / "state.json", self.log)
        self.override = d / "override.yml"

    def tearDown(self):
        self.tmp.cleanup()

    def env(self):
        return yaml.safe_load(self.override.read_text())["services"]

    def test_specs_shape(self):
        specs = load_specs(SPECS)
        self.assertEqual(sorted(specs), [f"fault_{i:02d}" for i in range(6, 11)])
        self.assertEqual(sum(s.cross_service for s in specs.values()), 2)
        for s in specs.values():
            if s.cross_service:
                self.assertNotEqual(s.culprit_service, s.symptom_service)
            self.assertTrue(s.keywords and s.expected_fix and s.root_cause)

    def test_apply_writes_override_recreates_and_emits_event(self):
        r = self.inj.apply("fault_06")
        self.assertTrue(r["changed"])
        self.assertEqual(self.env()["payments"]["environment"]["PAYMENTS_DB_QUERY_DELAY_MS"], "3000")
        self.assertEqual(self.runner.calls[-1][0:2], ("recreate", ("payments",)))
        ev = self.log.list()[-1]
        self.assertEqual((ev["type"], ev["service"]), ("config", "payments"))
        self.assertNotIn("fault", ev["message"].lower())  # no leak of the ground truth

    def test_apply_is_idempotent_and_revert_restores_baseline_three_times(self):
        for _ in range(3):
            self.assertTrue(self.inj.apply("fault_09")["changed"])
            self.assertFalse(self.inj.apply("fault_09")["changed"])
            self.assertEqual(self.inj.active(), ["fault_09"])
            self.assertTrue(self.inj.revert("fault_09")["changed"])
            self.assertEqual(self.inj.active(), [])
            self.assertEqual(self.env(), {})
        self.assertFalse(self.inj.revert("fault_09")["changed"])

    def test_two_faults_on_same_service_merge_then_partial_revert(self):
        self.inj.apply("fault_08")
        self.inj.apply("fault_10")
        env = self.env()["orders"]["environment"]
        self.assertEqual(set(env), {"ORDERS_DISCOUNT_ENGINE", "ORDERS_DB_POOL_SIZE"})
        self.inj.revert("fault_08")
        self.assertEqual(set(self.env()["orders"]["environment"]), {"ORDERS_DB_POOL_SIZE"})
        self.assertEqual(self.inj.revert_all(), ["fault_10"])

    def test_unknown_fault_and_ground_truth(self):
        with self.assertRaises(KeyError):
            self.inj.apply("fault_99")
        gt = self.inj.ground_truth("fault_07")
        self.assertEqual((gt["culprit_service"], gt["symptom_service"], gt["category"]), ("payments", "orders", "cross_service"))

    def test_runtime_flags(self):
        from faults.runtime_flags import env_int, payments_response
        os.environ["PAYMENTS_RESPONSE_SCHEMA"] = "v2"
        try:
            out = payments_response({"id": 1, "amount": 12.5})
            self.assertEqual(out, {"id": 1, "amount_cents": 1250})
        finally:
            del os.environ["PAYMENTS_RESPONSE_SCHEMA"]
        self.assertEqual(payments_response({"amount": 1}), {"amount": 1})
        self.assertEqual(env_int("NOT_SET_VAR", 7), 7)


if __name__ == "__main__":
    unittest.main()
