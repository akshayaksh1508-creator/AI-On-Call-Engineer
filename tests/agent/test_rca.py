import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import json, unittest

from agent.bundle_client import BundleClient
from agent.rca import (SUBMIT_SCHEMA, ScriptedLLM, ToolRouter, EvidenceStore, investigate,
                       validate_hypotheses)
from agent.rca_evaluator import evaluate, load_truths
from agent.synthetic_bundles import all_bundles, build_bundle

SPECS = os.path.join(os.path.dirname(__file__), "..", "..", "faults", "specs")


def submit(hyps):
    return [{"type": "tool_use", "id": "t-submit", "name": "submit_hypotheses", "input": {"hypotheses": hyps}}]


def tool(name, **args):
    return [{"type": "tool_use", "id": f"t-{name}", "name": name, "input": args}]


class RcaTests(unittest.TestCase):
    def run_fault(self, fid, llm=None, **kw):
        b = build_bundle(fid)
        return investigate(b["incident"], BundleClient(b), llm=llm, **kw)

    def test_changes_are_always_the_first_tool_call(self):
        for fid in ("fault_06", "fault_09"):
            out = self.run_fault(fid)
            self.assertEqual(out["tool_calls"][0]["tool"], "list_changes")
            self.assertIn("list_changes", [c["tool"] for c in out["tool_calls"][:3]])
            self.assertTrue(all(c["phase"] == "prefetch" for c in out["tool_calls"]))

    def test_old_changes_outside_window_are_ignored(self):
        out = self.run_fault("fault_09")
        changes = [e for e in out["evidence"] if e["type"] in ("config", "deploy")]
        self.assertEqual(len(changes), 1)  # the 2-hour-old gateway deploy is outside the 30 min window

    def test_cross_service_blames_upstream_service(self):
        for fid, culprit in (("fault_06", "payments"), ("fault_07", "payments")):
            out = self.run_fault(fid)
            self.assertEqual(out["suspects"][0]["service"], culprit, fid)
            self.assertEqual(out["hypotheses"][0]["category"], "cross_service")

    def test_heuristic_baseline_on_synthetic_bundles(self):
        truths = load_truths(SPECS)
        outs = {fid: investigate(b["incident"], BundleClient(b)) for fid, b in all_bundles().items()}
        res = evaluate(outs, truths)
        self.assertEqual(res["n"], 5)
        self.assertEqual(res["top1"], 5, res["per_fault"])  # smoke test only: synthetic data

    def test_llm_loop_validates_evidence_ids(self):
        llm = ScriptedLLM([
            tool("git_log", n=3),
            submit([
                {"cause": "payments config change slowed queries", "category": "cross_service",
                 "culprit_service": "payments", "confidence": 0.9, "evidence_ids": ["E2", "E999"]},
                {"cause": "just a guess", "category": "unknown", "culprit_service": "gateway",
                 "confidence": 0.8, "evidence_ids": []},
            ]),
        ])
        out = self.run_fault("fault_06", llm=llm)
        h1, h2 = out["hypotheses"]
        self.assertIn("unknown_evidence_ids", h1["flags"])
        self.assertEqual(h1["evidence_ids"], ["E2"])
        self.assertAlmostEqual(h1["confidence"], 0.45)
        self.assertIn("guess", h2["flags"])
        self.assertLessEqual(h2["confidence"], 0.3)
        self.assertEqual(out["llm_steps"], 1)
        self.assertFalse(out["fallback_used"])
        self.assertGreater(out["usage"]["input_tokens"], 0)
        self.assertEqual(out["prompt_version"], "v3")

    def test_llm_without_tool_use_gets_nudged_once(self):
        llm = ScriptedLLM([
            [{"type": "text", "text": "thinking..."}],
            submit([{"cause": "x", "category": "config", "culprit_service": "gateway", "confidence": 0.7, "evidence_ids": ["E1"]}]),
        ])
        out = self.run_fault("fault_09", llm=llm)
        self.assertFalse(out["fallback_used"])
        self.assertEqual(out["hypotheses"][0]["culprit_service"], "gateway")

    def test_step_budget_forces_submit_then_falls_back(self):
        llm = ScriptedLLM([tool("query_logs", text="timeout")])  # never submits
        out = self.run_fault("fault_06", llm=llm, max_steps=3)
        self.assertEqual(out["llm_steps"], 3)
        self.assertEqual(llm.seen_tools[-1], ["submit_hypotheses"])
        self.assertTrue(out["fallback_used"])
        self.assertTrue(out["hypotheses"])  # fallback still yields valid output

    def test_tool_error_does_not_crash(self):
        class Broken(BundleClient):
            def git_diff(self, **kw):
                raise RuntimeError("repo offline")
        b = build_bundle("fault_08")
        llm = ScriptedLLM([tool("git_diff", commit="abc"), submit([
            {"cause": "orders flag", "category": "code_bug", "culprit_service": "orders", "confidence": 0.8, "evidence_ids": ["E2"]}])])
        out = investigate(b["incident"], Broken(b), llm=llm)
        self.assertIn("RuntimeError", out["tool_calls"][-1]["error"])
        self.assertEqual(out["hypotheses"][0]["culprit_service"], "orders")

    def test_unavailable_tool_and_past_incidents_default(self):
        class Minimal:
            def list_changes(self, **kw):
                return {"changes": []}
        r = ToolRouter(Minimal(), EvidenceStore())
        self.assertIn("error", r.call("git_log", {}))
        self.assertEqual(r.call("search_past_incidents", {"query": "x"})["result"], {"results": []})

    def test_large_results_are_truncated(self):
        class Big:
            def query_logs(self, **kw):
                return {"entries": [{"service": "a", "level": "ERROR", "message": "x" * 200, "ts": i} for i in range(500)]}
        r = ToolRouter(Big(), EvidenceStore(), max_chars=3000)
        res = r.call("query_logs", {})
        self.assertLessEqual(len(json.dumps(res)), 3200)
        self.assertTrue(res.get("truncated"))

    def test_validate_clamps_and_sorts(self):
        store = EvidenceStore()
        eid = store.add("log", "r", "x")
        out = validate_hypotheses([
            {"cause": "a", "category": "weird", "culprit_service": "s", "confidence": 5, "evidence_ids": [eid]},
            {"cause": "b", "category": "config", "culprit_service": "s", "confidence": 0.2, "evidence_ids": [eid]}], store)
        self.assertEqual(out[0]["confidence"], 1.0)
        self.assertEqual(out[0]["category"], "unknown")
        self.assertEqual([h["cause"] for h in out], ["a", "b"])

    def test_submit_schema_allows_max_three(self):
        self.assertEqual(SUBMIT_SCHEMA["input_schema"]["properties"]["hypotheses"]["maxItems"], 3)


if __name__ == "__main__":
    unittest.main()
