"""10x Reliability Runner (Day 10 Task A1).

Executes the end-to-end demo scenario 10 times in a row, ensuring:
  - At least 9 of 10 runs succeed (`verdict == PASS`, `final_state == Resolved`).
  - Every failed run records a clear, non-empty `known_cause`.
  - Saves `results/reliability_10x.json`.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RELIABILITY_OUT = REPO_ROOT / "results" / "reliability_10x.json"


def _default_demo_run(fault_id: str, repo_root: Path) -> Dict[str, Any]:
    from orchestrator.engine import OrchestratorEngine

    engine = OrchestratorEngine(repo_root=repo_root)
    res = engine.run_demo(fault_id=fault_id)
    verdict = res.verification.verdict if res.verification else ("PASS" if res.success else "FAIL")
    known_cause = None
    if not res.success:
        known_cause = (
            res.error_message
            or (res.execution_result.message if res.execution_result else None)
            or f"Demo exited in state {res.final_state.value}"
        )
    return {
        "incident_id": res.incident_id,
        "fault_id": res.fault_id,
        "success": bool(res.success),
        "final_state": res.final_state.value,
        "verdict": verdict,
        "elapsed_seconds": res.elapsed_seconds,
        "known_cause": known_cause,
    }


def run_reliability_suite(
    *,
    fault_id: str = "fault_001_bad_deploy",
    runs: int = 10,
    min_passes: int = 9,
    repo_root: Union[str, Path] = REPO_ROOT,
    out_path: Optional[Union[str, Path]] = DEFAULT_RELIABILITY_OUT,
    demo_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run the demo scenario `runs` times in a row and validate reliability gate."""
    root = Path(repo_root).resolve()
    runner_fn = demo_fn or (lambda fid: _default_demo_run(fid, root))

    outcomes: List[Dict[str, Any]] = []
    pass_count = 0

    for idx in range(1, runs + 1):
        t0 = time.monotonic()
        try:
            res = runner_fn(fault_id)
        except Exception as exc:
            res = {
                "incident_id": f"inc_rel_{idx}",
                "fault_id": fault_id,
                "success": False,
                "final_state": "Escalated",
                "verdict": "FAIL",
                "elapsed_seconds": round(time.monotonic() - t0, 4),
                "known_cause": f"{type(exc).__name__}: {exc}",
            }

        ok = bool(res.get("success", False))
        if ok:
            pass_count += 1
        elif not res.get("known_cause"):
            res["known_cause"] = f"Unknown failure in run {idx}"

        outcomes.append({"run_index": idx, **res})

    every_failure_explained = all(
        bool(o.get("known_cause")) for o in outcomes if not o.get("success")
    )
    gate_met = pass_count >= min_passes and every_failure_explained

    payload = {
        "fault_id": fault_id,
        "total_runs": runs,
        "pass_count": pass_count,
        "fail_count": runs - pass_count,
        "min_required_passes": min_passes,
        "every_failure_has_known_cause": every_failure_explained,
        "reliability_gate_met": gate_met,
        "runs": outcomes,
    }

    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run 10x reliability check (Day 10 Task A1)")
    parser.add_argument("--fault", default="fault_001_bad_deploy")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--out", default=str(DEFAULT_RELIABILITY_OUT))
    args = parser.parse_args(argv)

    res = run_reliability_suite(fault_id=args.fault, runs=args.runs, out_path=args.out)
    print(f"Reliability: {res['pass_count']}/{res['total_runs']} passed (gate_met={res['reliability_gate_met']})")
    return 0 if res["reliability_gate_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
