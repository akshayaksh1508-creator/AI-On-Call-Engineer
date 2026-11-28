"""Day 12 Task B3 — Submission Materials Check Against Section 12.

Programmatically verifies all 14 items in Section 12 of
`AI On-Call Engineer Architecture and 12-Day Execution Plan.md` and writes
the ticked checklist to `pitch/section12_checklist.md`.

Owner: Person B (Brain & Trust)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from pitch.cross_check import cross_check_deck_against_final_json

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHECKLIST_MD = REPO_ROOT / "pitch" / "section12_checklist.md"


def _exists_nonempty(rel_path: str) -> bool:
    p = REPO_ROOT / rel_path
    return p.exists() and p.stat().st_size > 0


def run_section12_checklist(
    *,
    output_md: Path = DEFAULT_CHECKLIST_MD,
) -> Dict[str, Any]:
    final_json_path = REPO_ROOT / "results" / "final.json"
    final_data = json.loads(final_json_path.read_text(encoding="utf-8")) if final_json_path.exists() else {}
    summary = final_data.get("summary", {})
    held_out = final_data.get("held_out_summary", {})
    cross_check = cross_check_deck_against_final_json()

    ablation_files = list((REPO_ROOT / "results" / "ablations").glob("*.json")) if (REPO_ROOT / "results" / "ablations").exists() else []
    chart_files = list((REPO_ROOT / "results" / "final_charts").glob("*")) if (REPO_ROOT / "results" / "final_charts").exists() else []

    items: List[Dict[str, Any]] = [
        {
            "id": 1,
            "item": "Live demo works on a clean machine with one command",
            "passed": _exists_nonempty("scripts/setup_clean_machine.ps1")
            and _exists_nonempty("scripts/setup_clean_machine.sh")
            and _exists_nonempty("results/day12_env_freeze_checklist.json"),
            "evidence": "scripts/setup_clean_machine.{ps1,sh}, results/day12_env_freeze_checklist.json",
        },
        {
            "id": 2,
            "item": "Benchmark of 20 or more incidents with results.json and charts",
            "passed": summary.get("total_runs", 0) >= 20 and len(chart_files) >= 5,
            "evidence": f"results/final.json (total_runs={summary.get('total_runs', 0)}), results/final_charts/ ({len(chart_files)} files)",
        },
        {
            "id": 3,
            "item": "Held-out set reported separately",
            "passed": held_out.get("total_runs", 0) >= 5,
            "evidence": f"held_out_summary in results/final.json (total_runs={held_out.get('total_runs', 0)})",
        },
        {
            "id": 4,
            "item": "Human baseline MTTR measured",
            "passed": _exists_nonempty("results/human_baseline.json") and _exists_nonempty("results/human_baseline.md"),
            "evidence": "results/human_baseline.json, results/human_baseline.md",
        },
        {
            "id": 5,
            "item": "At least 2 ablations",
            "passed": len(ablation_files) >= 2,
            "evidence": f"results/ablations/ ({len(ablation_files)} ablation files)",
        },
        {
            "id": 6,
            "item": "Failure analysis table",
            "passed": _exists_nonempty("results/final_failure_table.md") and _exists_nonempty("results/final_failure_table.json"),
            "evidence": "results/final_failure_table.md, results/final_failure_table.json",
        },
        {
            "id": 7,
            "item": "Safety tiers, auto-rollback and kill switch demonstrated",
            "passed": _exists_nonempty("results/safety_demo_rehearsal.json") and _exists_nonempty("safety/gate.py"),
            "evidence": "results/safety_demo_rehearsal.json, safety/gate.py",
        },
        {
            "id": 8,
            "item": "Cross-service incident demonstrated",
            "passed": any(
                r.get("fault_id") == "fault_017_symptom_gw_cause_payments" and r.get("fix_ok")
                for r in final_data.get("records", [])
            ),
            "evidence": "fault_017_symptom_gw_cause_payments in results/final.json",
        },
        {
            "id": 9,
            "item": "Memory benefit measured",
            "passed": _exists_nonempty("results/memory_experiment.json"),
            "evidence": "results/memory_experiment.json",
        },
        {
            "id": 10,
            "item": "Cost per incident computed",
            "passed": summary.get("mean_cost_usd", 0) > 0 and summary.get("total_cost_usd", 0) > 0,
            "evidence": f"mean_cost_usd=${summary.get('mean_cost_usd', 0):.4f}, total_cost_usd=${summary.get('total_cost_usd', 0):.4f}",
        },
        {
            "id": 11,
            "item": "Curveball prepared and rehearsed",
            "passed": _exists_nonempty("results/curveball_results.json") and _exists_nonempty("results/day12_live_rehearsal.json"),
            "evidence": "results/curveball_results.json, results/day12_live_rehearsal.json",
        },
        {
            "id": 12,
            "item": "Backup video and offline fallback ready",
            "passed": _exists_nonempty("results/demo_backup_video.gif")
            and _exists_nonempty("results/demo_backup_video.html")
            and _exists_nonempty("results/recorded_replay_fault_001.json"),
            "evidence": "results/demo_backup_video.{gif,webp,html}, results/recorded_replay_fault_001.json",
        },
        {
            "id": 13,
            "item": "Business case slide and Q&A prepared",
            "passed": _exists_nonempty("pitch/deck_final.md") and _exists_nonempty("pitch/qa_bank.md"),
            "evidence": "pitch/deck_final.md, pitch/qa_bank.md",
        },
        {
            "id": 14,
            "item": "Every slide number matches results.json",
            "passed": bool(cross_check.get("passed")),
            "evidence": f"pitch/cross_check.py ({len(cross_check.get('checked_fields', []))} fields verified)",
        },
    ]

    all_passed = all(it["passed"] for it in items)
    report: Dict[str, Any] = {
        "task": "Day 12 B3 - Section 12 Submission Checklist",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_items": len(items),
        "passed_items": sum(1 for it in items if it["passed"]),
        "all_passed": all_passed,
        "items": items,
    }

    lines = [
        "# NightShift — Day 12 Section 12 Final Submission Checklist (`B3`)",
        "",
        f"- **Verified (UTC):** {report['generated_at_utc']}",
        f"- **Score:** {report['passed_items']}/{report['total_items']} ticked",
        f"- **Status:** {'ALL CHECKED' if all_passed else 'INCOMPLETE'}",
        "",
    ]
    for it in items:
        mark = "x" if it["passed"] else " "
        lines.append(f"- [{mark}] **{it['id']}. {it['item']}** — `{it['evidence']}`")

    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run_section12_checklist()
    print(json.dumps(result, indent=2))
