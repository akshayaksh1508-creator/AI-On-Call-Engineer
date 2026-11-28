"""Day 12 Task A2 — Two Consecutive Live Demo Runs + One Curveball.

Runs two consecutive end-to-end demo incidents on the demo machine and one
unseen curveball fault. Verifies:
- Both consecutive live runs reach a verified recovery (`fix_ok == True`, `unsafe == False`).
- The curveball ends in either a verified fix or a safe escalation (`unsafe == False`).

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

from bench.final_bench import default_final_orchestrate
from bench.runner import BenchmarkRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REHEARSAL_JSON = REPO_ROOT / "results" / "day12_live_rehearsal.json"
DEFAULT_REHEARSAL_MD = REPO_ROOT / "results" / "day12_live_rehearsal.md"

DEFAULT_LIVE_FAULTS = ("fault_001_bad_deploy", "fault_017_symptom_gw_cause_payments")
DEFAULT_CURVEBALL_FAULT = "fault_016_slow_query_missing_index"


def run_day12_live_rehearsal(
    *,
    live_faults: tuple[str, str] = DEFAULT_LIVE_FAULTS,
    curveball_fault: str = DEFAULT_CURVEBALL_FAULT,
    orchestrator_fn: Callable[[str], Dict[str, Any]] = default_final_orchestrate,
    output_json: Path = DEFAULT_REHEARSAL_JSON,
    output_md: Path = DEFAULT_REHEARSAL_MD,
    confirm_healthy_seconds: float = 0.0,
) -> Dict[str, Any]:
    runner = BenchmarkRunner(
        repo_root=REPO_ROOT,
        orchestrate_fn=orchestrator_fn,
        confirm_healthy_seconds=confirm_healthy_seconds,
        sleep_fn=lambda _: None,
    )

    live_runs: List[Dict[str, Any]] = []
    for idx, fault_id in enumerate(live_faults, start=1):
        entry = runner.run_fault(fault_id)
        rec = entry.run_record
        live_runs.append(
            {
                "run_index": idx,
                "fault_id": rec.fault_id,
                "incident_id": rec.incident_id,
                "verified_recovery": bool(rec.fix_ok and not rec.unsafe),
                "rca_top1": bool(rec.rca_correct_top1),
                "rca_top3": bool(rec.rca_correct_top3),
                "unsafe": bool(rec.unsafe),
                "total_time_s": round(rec.t_detect + rec.t_rca + rec.t_fix + rec.t_verified, 3),
                "tokens": rec.tokens,
                "cost_usd": rec.cost_usd,
            }
        )

    cb_entry = runner.run_fault(curveball_fault)
    cb_rec = cb_entry.run_record
    cb_outcome = "verified_fix" if (cb_rec.fix_ok and not cb_rec.unsafe) else (
        "safe_escalation" if not cb_rec.unsafe else "unsafe_action"
    )
    curveball_result = {
        "fault_id": cb_rec.fault_id,
        "incident_id": cb_rec.incident_id,
        "outcome": cb_outcome,
        "fix_ok": bool(cb_rec.fix_ok),
        "rca_top1": bool(cb_rec.rca_correct_top1),
        "rca_top3": bool(cb_rec.rca_correct_top3),
        "unsafe": bool(cb_rec.unsafe),
        "total_time_s": round(cb_rec.t_detect + cb_rec.t_rca + cb_rec.t_fix + cb_rec.t_verified, 3),
        "tokens": cb_rec.tokens,
        "cost_usd": cb_rec.cost_usd,
    }

    consecutive_ok = len(live_runs) == 2 and all(r["verified_recovery"] for r in live_runs)
    curveball_ok = curveball_result["outcome"] in ("verified_fix", "safe_escalation")
    all_passed = consecutive_ok and curveball_ok

    report: Dict[str, Any] = {
        "task": "Day 12 A2 - Two Consecutive Live Runs + Curveball",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "all_passed": all_passed,
        "consecutive_live_runs_passed": consecutive_ok,
        "curveball_passed": curveball_ok,
        "live_runs": live_runs,
        "curveball": curveball_result,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Day 12 Task A2 — Live Demo Rehearsal & Curveball Report",
        "",
        f"- **Generated (UTC):** {report['generated_at_utc']}",
        f"- **Overall Status:** {'PASS' if all_passed else 'FAIL'}",
        "",
        "## Consecutive Live Runs",
        "",
        "| Run | Fault ID | Verified Recovery | Top-1 RCA | Unsafe | Time (s) | Cost (USD) |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in live_runs:
        lines.append(
            f"| {r['run_index']} | `{r['fault_id']}` | {r['verified_recovery']} | "
            f"{r['rca_top1']} | {r['unsafe']} | {r['total_time_s']} | ${r['cost_usd']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Curveball Run",
            "",
            f"- **Fault ID:** `{curveball_result['fault_id']}`",
            f"- **Outcome:** `{curveball_result['outcome']}`",
            f"- **Unsafe:** {curveball_result['unsafe']}",
            f"- **Time (s):** {curveball_result['total_time_s']}",
        ]
    )
    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run_day12_live_rehearsal()
    print(json.dumps(result, indent=2))
