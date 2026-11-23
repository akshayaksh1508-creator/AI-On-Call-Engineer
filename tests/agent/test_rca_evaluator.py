import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import unittest

from agent.rca_evaluator import evaluate, hypothesis_matches, outputs_from_runs

T = {
    "f1": {"id": "f1", "category": "cross_service", "culprit_service": "payments", "keywords": ["slow"]},
    "f2": {"id": "f2", "category": "config", "culprit_service": "gateway", "keywords": ["timeout"]},
    "f3": {"id": "f3", "category": "resource", "culprit_service": "orders", "keywords": ["pool"]},
}


def h(svc, cat, cause="x"):
    return {"culprit_service": svc, "category": cat, "cause": cause, "confidence": 0.5}


class EvaluatorTests(unittest.TestCase):
    def test_match_rules(self):
        self.assertTrue(hypothesis_matches(h("payments", "cross_service"), T["f1"]))
        self.assertTrue(hypothesis_matches(h("payments", "code_bug", "query is SLOW"), T["f1"]))  # keyword fallback
        self.assertFalse(hypothesis_matches(h("gateway", "cross_service", "slow"), T["f1"]))  # wrong service
        self.assertFalse(hypothesis_matches(h("payments", "code_bug", "nothing"), T["f1"]))

    def test_top1_top3_and_categories(self):
        outs = {
            "f1": {"hypotheses": [h("payments", "cross_service")]},                          # top1 right
            "f2": {"hypotheses": [h("orders", "config"), h("gateway", "config")]},           # top3 only
            "f3": {"hypotheses": [h("gateway", "config")] * 3},                               # wrong
        }
        r = evaluate(outs, T)
        self.assertEqual((r["n"], r["top1"], r["top3"]), (3, 1, 2))
        self.assertEqual(r["top1_rate"], 0.333)
        self.assertEqual(r["by_category"]["config"], {"n": 1, "top1": 0, "top3": 1})
        self.assertTrue(r["per_fault"]["f1"]["top1"] and not r["per_fault"]["f3"]["top3"])

    def test_missed_runs_count_as_wrong(self):
        outs = outputs_from_runs([{"fault_id": "f1", "status": "detector_miss"}, {"fault_id": "f2", "output": {"hypotheses": [h("gateway", "config")]}}])
        r = evaluate(outs, T)
        self.assertEqual((r["n"], r["top1"]), (2, 1))


if __name__ == "__main__":
    unittest.main()
