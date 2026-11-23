"""Compare agent output with fault ground truth (Day 3, B2).

Match rule: a hypothesis is correct if
    culprit_service == truth.culprit_service
    AND (category == truth.category OR any truth keyword appears in cause/culprit_change text).
Top-1 = first hypothesis correct; top-3 = any of the first three correct.

    python -m agent.rca_evaluator --runs results/rca_day3_runs.json --faults faults/specs --out results/rca_day3.json
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


def load_truths(specs_dir: str | Path) -> dict[str, dict[str, Any]]:
    out = {}
    for p in sorted(Path(specs_dir).glob("*.y*ml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        out[d["id"]] = d
    return out


def hypothesis_matches(h: dict[str, Any], truth: dict[str, Any]) -> bool:
    if str(h.get("culprit_service", "")).lower() != str(truth["culprit_service"]).lower():
        return False
    if h.get("category") == truth["category"]:
        return True
    text = f"{h.get('cause', '')} {h.get('culprit_change', '')}".lower()
    return any(str(k).lower() in text for k in truth.get("keywords", []))


def evaluate(outputs: dict[str, dict[str, Any]], truths: dict[str, dict[str, Any]]) -> dict[str, Any]:
    per_fault, by_cat = {}, defaultdict(lambda: {"n": 0, "top1": 0, "top3": 0})
    n = top1 = top3 = 0
    for fid, out in outputs.items():
        truth = truths.get(fid)
        if truth is None:
            continue
        hyps = (out or {}).get("hypotheses", [])
        t1 = bool(hyps) and hypothesis_matches(hyps[0], truth)
        t3 = any(hypothesis_matches(h, truth) for h in hyps[:3])
        per_fault[fid] = {"category": truth["category"], "top1": t1, "top3": t3,
                          "predicted": [(h.get("culprit_service"), h.get("category"), h.get("confidence")) for h in hyps[:3]]}
        n += 1
        top1 += t1
        top3 += t3
        c = by_cat[truth["category"]]
        c["n"] += 1
        c["top1"] += t1
        c["top3"] += t3
    return {
        "n": n, "top1": top1, "top3": top3,
        "top1_rate": round(top1 / n, 3) if n else None, "top3_rate": round(top3 / n, 3) if n else None,
        "by_category": dict(by_cat), "per_fault": per_fault,
    }


def outputs_from_runs(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Runs where the detector missed or the agent crashed count as wrong (empty hypotheses)."""
    return {r["fault_id"]: (r.get("output") or {"hypotheses": []}) for r in runs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--faults", default="faults/specs")
    ap.add_argument("--out", default="results/rca_day3.json")
    a = ap.parse_args()
    runs = json.loads(Path(a.runs).read_text())
    result = evaluate(outputs_from_runs(runs), load_truths(a.faults))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, indent=2))
    print(f"top-1 {result['top1']}/{result['n']}  top-3 {result['top3']}/{result['n']} -> {a.out}")


if __name__ == "__main__":
    main()
