"""Run prompt versions over bundles and log the accuracy delta (Day 3, B3).

    python -m agent.prompt_iter --synthetic --versions v1 v2 v3            # heuristic smoke test (no API)
    python -m agent.prompt_iter --bundles-dir tests/fixtures/bundles --versions v1 v2 v3 --llm anthropic

Appends a row per version to results/prompt_changelog.md with the delta vs the previous version.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from agent.bundle_client import BundleClient
from agent.rca import AnthropicLLM, investigate
from agent.rca_evaluator import evaluate, load_truths
from agent.synthetic_bundles import all_bundles


def run_version(bundles: dict, truths: dict, version: str, llm) -> dict:
    outputs = {}
    for fid, b in bundles.items():
        outputs[fid] = investigate(b["incident"], BundleClient(b), llm=llm, prompt_version=version)
    res = evaluate(outputs, truths)
    res["cost_usd"] = round(sum(o["cost_usd"] for o in outputs.values()), 4)
    res["avg_tool_calls"] = round(sum(len(o["tool_calls"]) for o in outputs.values()) / max(1, len(outputs)), 1)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundles-dir")
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--faults", default="faults/specs")
    ap.add_argument("--versions", nargs="+", default=["v1", "v2", "v3"])
    ap.add_argument("--llm", choices=["none", "anthropic"], default="none")
    ap.add_argument("--log", default="results/prompt_changelog.md")
    a = ap.parse_args()
    if a.synthetic:
        bundles = all_bundles()
    else:
        bundles = {}
        for p in sorted(Path(a.bundles_dir).glob("*.json")):
            b = json.loads(p.read_text())
            bundles[b["fault_id"]] = b
    truths = load_truths(a.faults)
    llm = AnthropicLLM() if a.llm == "anthropic" else None
    log = Path(a.log)
    log.parent.mkdir(parents=True, exist_ok=True)
    if not log.exists():
        log.write_text("# Prompt change log\n\n| time | version | llm | n | top-1 | top-3 | delta top-1 | avg tool calls | cost USD |\n|---|---|---|---|---|---|---|---|---|\n")
    prev = None
    for v in a.versions:
        r = run_version(bundles, truths, v, llm)
        delta = "" if prev is None else f"{r['top1'] - prev:+d}"
        prev = r["top1"]
        row = f"| {datetime.now():%Y-%m-%d %H:%M} | {v} | {a.llm} | {r['n']} | {r['top1']} | {r['top3']} | {delta} | {r['avg_tool_calls']} | {r['cost_usd']} |\n"
        with log.open("a") as fh:
            fh.write(row)
        print(row.strip())


if __name__ == "__main__":
    main()
