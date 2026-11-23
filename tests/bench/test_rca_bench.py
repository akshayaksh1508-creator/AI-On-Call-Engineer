import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import unittest

from bench.rca_bench import run_bench


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeIncidents:
    def __init__(self):
        self.items = []

    def list(self):
        return list(self.items)


class FakeInjector:
    def __init__(self, incidents, miss=()):
        self.incidents, self.miss, self.active, self.reverted = incidents, set(miss), [], []

    def apply(self, fid):
        self.active.append(fid)
        if fid not in self.miss:
            self.incidents.items.append({"id": f"inc-{fid}", "service": "gateway", "started_at": 1.0})

    def revert(self, fid):
        self.reverted.append(fid)


class BenchTests(unittest.TestCase):
    def run_it(self, faults, miss=(), crash=()):
        clock, inc = Clock(), FakeIncidents()
        inj = FakeInjector(inc, miss)

        def investigate(i):
            if i["id"].replace("inc-", "") in crash:
                raise RuntimeError("boom")
            return {"hypotheses": [{"culprit_service": "payments"}]}

        runs = run_bench(faults, inj, inc, investigate, lambda: True, 10, 10, clock.sleep, clock)
        return runs, inj

    def test_happy_path_records_timings_and_reverts(self):
        runs, inj = self.run_it(["fault_06", "fault_07"])
        self.assertEqual([r["status"] for r in runs], ["ok", "ok"])
        self.assertTrue(all("t_detect_s" in r and "output" in r and r["recovered"] for r in runs))
        self.assertEqual(inj.reverted, ["fault_06", "fault_07"])

    def test_detector_miss_and_agent_crash_do_not_stop_the_run(self):
        runs, inj = self.run_it(["fault_06", "fault_07", "fault_08"], miss=["fault_06"], crash=["fault_07"])
        self.assertEqual(runs[0]["status"], "detector_miss")
        self.assertTrue(runs[1]["status"].startswith("agent_error"))
        self.assertEqual(runs[2]["status"], "ok")
        self.assertEqual(inj.reverted, ["fault_06", "fault_07", "fault_08"])  # always reverts


if __name__ == "__main__":
    unittest.main()
