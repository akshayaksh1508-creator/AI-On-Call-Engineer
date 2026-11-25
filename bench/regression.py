"""Benchmark Regression Suite (Day 8 Task A4).

Re-runs all previously passing faults from a baseline results file (e.g. `results/v1.json`)
after each code/prompt change, enforces the 30-minute runtime budget, and reports
any newly introduced regressions.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from bench.runner import BenchmarkRunner
from bench.v1_runner import default_v1_orchestrate

REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_REGRESSION_BUDGET_SECONDS = 1800.0  # 30 minutes


@dataclass
class RegressionReport:
    """Outcome of running the regression suite on previously passing faults."""

    baseline_passing_faults: List[str]
    total_checked: int
    passed_count: int
    regressions: List[str]
    elapsed_seconds: float
    within_budget: bool
    passed: bool
    details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def extract_passing_faults(baseline_results: Union[str, Path, Dict[str, Any]]) -> List[str]:
    """Extract all fault IDs that passed in a baseline results payload/file."""
    if isinstance(baseline_results, (str, Path)):
        data = json.loads(Path(baseline_results).read_text(encoding="utf-8"))
    else:
        data = baseline_results

    passing: List[str] = []
    for entry in data.get("runs", []):
        rec = entry.get("run_record") or {}
        if entry.get("status") == "pass" and bool(rec.get("fix_ok", False)):
            fid = entry.get("fault_id")
            if fid:
                passing.append(fid)
    return passing


class RegressionSuite:
    """Re-runs previously passing faults and flags any newly broken fault."""

    def __init__(
        self,
        *,
        repo_root: Union[str, Path] = REPO_ROOT,
        orchestrate_fn: Optional[Callable[[str], Any]] = None,
        budget_seconds: float = MAX_REGRESSION_BUDGET_SECONDS,
        confirm_healthy_seconds: float = 0.01,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.orchestrate_fn = orchestrate_fn or (
            lambda fid: default_v1_orchestrate(fid, repo_root=self.repo_root)
        )
        self.budget_seconds = float(budget_seconds)
        self.confirm_healthy_seconds = float(confirm_healthy_seconds)

    def run(
        self,
        passing_faults: Sequence[str],
        *,
        out_path: Optional[Union[str, Path]] = None,
    ) -> RegressionReport:
        t_start = time.monotonic()
        runner = BenchmarkRunner(
            repo_root=self.repo_root,
            orchestrate_fn=self.orchestrate_fn,
            confirm_healthy_seconds=self.confirm_healthy_seconds,
            health_poll_interval=0.005,
        )

        regressions: List[str] = []
        details: List[Dict[str, Any]] = []
        passed_count = 0

        for fid in passing_faults:
            entry = runner.run_fault(fid)
            ok = entry.status == "pass" and entry.run_record.fix_ok
            if ok:
                passed_count += 1
            else:
                regressions.append(fid)
            details.append({
                "fault_id": fid,
                "status": entry.status,
                "fix_ok": entry.run_record.fix_ok,
                "reason": entry.classification_reason,
            })

        elapsed = round(time.monotonic() - t_start, 4)
        within_budget = elapsed < self.budget_seconds
        report = RegressionReport(
            baseline_passing_faults=list(passing_faults),
            total_checked=len(passing_faults),
            passed_count=passed_count,
            regressions=regressions,
            elapsed_seconds=elapsed,
            within_budget=within_budget,
            passed=(len(regressions) == 0 and within_budget),
            details=details,
        )

        if out_path is not None:
            out_file = Path(out_path)
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")

        return report
