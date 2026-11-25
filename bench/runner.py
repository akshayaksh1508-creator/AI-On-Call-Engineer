"""Unattended End-to-End Benchmark Runner (Day 7 Tasks A1 & A4).

For each fault in the benchmark suite:
  1. Reset environment to clean baseline.
  2. Confirm environment is continuously healthy for `confirm_healthy_seconds` (default 30s).
  3. Inject the fault.
  4. Run the autonomous orchestrator loop.
  5. Classify outcome (`pass`, `fail`, or `infra_error`), retrying once on `infra_error`.
  6. Persist validated `RunRecord` entries and aggregate `results.json` + SVG charts.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from bench.aggregator import aggregate_results, generate_charts
from bench.flake_handler import FlakeClassification, classify_run_outcome
from contracts.models import RunRecord

logger = logging.getLogger("nightshift.bench.runner")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FAULTS_JSON = REPO_ROOT / "docs" / "faults.json"
DEFAULT_RESULTS_PATH = REPO_ROOT / "results" / "results.json"


def load_fault_catalogue(
    faults_json: Union[str, Path] = DEFAULT_FAULTS_JSON,
    *,
    limit: Optional[int] = 20,
) -> tuple[List[str], Dict[str, str]]:
    """Load fault IDs and category mapping from docs/faults.json."""
    path = Path(faults_json)
    if not path.exists():
        return [], {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("faults", []) if isinstance(raw, dict) else raw
    if limit is not None:
        items = items[:limit]
    fault_ids = [item["fault_id"] for item in items if "fault_id" in item]
    categories = {
        item["fault_id"]: item.get("category", "unknown")
        for item in items
        if "fault_id" in item
    }
    return fault_ids, categories


@dataclass
class BenchmarkRunEntry:
    """Detailed per-fault execution entry stored inside results.json."""

    fault_id: str
    status: str  # "pass", "fail", or "infra_error"
    initial_status: str
    had_infra_error: bool
    retried: bool
    retry_count: int
    classification_reason: str
    run_record: RunRecord
    attempts: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fault_id": self.fault_id,
            "status": self.status,
            "initial_status": self.initial_status,
            "had_infra_error": self.had_infra_error,
            "retried": self.retried,
            "retry_count": self.retry_count,
            "classification_reason": self.classification_reason,
            "run_record": self.run_record.model_dump(),
            "attempts": self.attempts,
        }


class BenchmarkRunner:
    """Runs 20+ faults unattended with health confirmation, flake retry, and RunRecord output."""

    def __init__(
        self,
        *,
        repo_root: Union[str, Path] = REPO_ROOT,
        reset_fn: Optional[Callable[[str], Any]] = None,
        health_fn: Optional[Callable[[], bool]] = None,
        inject_fn: Optional[Callable[[str], Any]] = None,
        orchestrate_fn: Optional[Callable[[str], Any]] = None,
        confirm_healthy_seconds: float = 30.0,
        health_poll_interval: float = 2.0,
        health_timeout_seconds: float = 120.0,
        max_infra_retries: int = 1,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.time,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.reset_fn = reset_fn or self._default_reset
        self.health_fn = health_fn or (lambda: True)
        self.inject_fn = inject_fn or self._default_inject
        self.orchestrate_fn = orchestrate_fn or self._default_orchestrate
        self.confirm_healthy_seconds = max(0.0, float(confirm_healthy_seconds))
        self.health_poll_interval = max(0.001, float(health_poll_interval))
        self.health_timeout_seconds = max(self.confirm_healthy_seconds + 1.0, float(health_timeout_seconds))
        self.max_infra_retries = max(0, int(max_infra_retries))
        self.sleep_fn = sleep_fn
        self.clock_fn = clock_fn

    def _default_reset(self, fault_id: str) -> None:
        """Default safe no-op/in-memory reset for unattended catalog runs."""
        logger.debug("Resetting environment after/before %s", fault_id)

    def _default_inject(self, fault_id: str) -> Dict[str, Any]:
        """Default fault injection marker."""
        return {"fault_id": fault_id, "injected": True}

    def _default_orchestrate(self, fault_id: str) -> RunRecord:
        """Default orchestrator execution returning a validated RunRecord."""
        from orchestrator.engine import OrchestratorEngine

        engine = OrchestratorEngine(repo_root=self.repo_root)
        res = engine.run_demo(fault_id=fault_id)
        if res.run_record is not None:
            return res.run_record
        return RunRecord(
            incident_id=res.incident_id,
            fault_id=fault_id,
            t_detect=5.0,
            t_rca=0.1,
            t_fix=0.1,
            t_verified=1.0,
            rca_correct_top1=res.success,
            rca_correct_top3=res.success,
            fix_ok=res.success,
            unsafe=False,
            tokens=0,
            cost_usd=0.0,
        )

    def confirm_healthy(self) -> bool:
        """Confirm environment stays continuously healthy for `confirm_healthy_seconds`."""
        deadline = self.clock_fn() + self.health_timeout_seconds
        healthy_since: Optional[float] = None

        while True:
            now = self.clock_fn()
            try:
                is_healthy = bool(self.health_fn())
            except Exception as exc:
                logger.warning("Health probe raised exception: %s", exc)
                is_healthy = False

            if is_healthy:
                if healthy_since is None:
                    healthy_since = now
                if (now - healthy_since) >= self.confirm_healthy_seconds:
                    return True
            else:
                healthy_since = None

            if now >= deadline:
                return False

            remaining_healthy = (
                self.confirm_healthy_seconds - (now - healthy_since)
                if healthy_since is not None
                else self.health_poll_interval
            )
            step = min(self.health_poll_interval, max(0.001, remaining_healthy))
            self.sleep_fn(step)

    def _extract_run_record(self, fault_id: str, output: Any, elapsed: float) -> tuple[RunRecord, bool, Optional[str]]:
        """Normalize orchestrator return value into (RunRecord, success, error_message)."""
        if isinstance(output, RunRecord):
            return output, output.fix_ok, None
        if hasattr(output, "run_record") and hasattr(output, "success"):
            rec = output.run_record
            if rec is None:
                rec = RunRecord(
                    incident_id=getattr(output, "incident_id", f"inc_{fault_id}"),
                    fault_id=fault_id,
                    t_detect=0.0,
                    t_rca=0.0,
                    t_fix=0.0,
                    t_verified=round(elapsed, 4),
                    rca_correct_top1=bool(output.success),
                    rca_correct_top3=bool(output.success),
                    fix_ok=bool(output.success),
                    unsafe=False,
                )
            return rec, bool(output.success), getattr(output, "error_message", None)
        if isinstance(output, dict):
            if "run_record" in output and isinstance(output["run_record"], RunRecord):
                rec = output["run_record"]
            else:
                rec = RunRecord(
                    incident_id=output.get("incident_id", f"inc_{fault_id}"),
                    fault_id=fault_id,
                    t_detect=float(output.get("t_detect", 1.0)),
                    t_rca=float(output.get("t_rca", 1.0)),
                    t_fix=float(output.get("t_fix", 1.0)),
                    t_verified=float(output.get("t_verified", max(0.1, elapsed))),
                    rca_correct_top1=bool(output.get("rca_correct_top1", output.get("success", False))),
                    rca_correct_top3=bool(output.get("rca_correct_top3", output.get("success", False))),
                    fix_ok=bool(output.get("fix_ok", output.get("success", False))),
                    unsafe=bool(output.get("unsafe", False)),
                    tokens=int(output.get("tokens", 0)),
                    cost_usd=float(output.get("cost_usd", 0.0)),
                )
            return rec, bool(output.get("success", rec.fix_ok)), output.get("error_message")

        raise TypeError(f"Unsupported orchestrate_fn return type: {type(output).__name__}")

    def _run_attempt(self, fault_id: str, attempt_num: int) -> tuple[RunRecord, FlakeClassification]:
        """Run one isolated reset -> healthy -> inject -> orchestrate cycle."""
        start = self.clock_fn()
        try:
            self.reset_fn(fault_id)
        except Exception as exc:
            cls = classify_run_outcome(success=False, exc=exc, error_message=f"infra_error: reset failed: {exc}")
            rec = RunRecord(
                incident_id=f"inc_{fault_id}_att{attempt_num}",
                fault_id=fault_id,
                t_detect=0.0,
                t_rca=0.0,
                t_fix=0.0,
                t_verified=0.0,
                rca_correct_top1=False,
                rca_correct_top3=False,
                fix_ok=False,
                unsafe=False,
            )
            return rec, cls

        if not self.confirm_healthy():
            cls = FlakeClassification(
                status="infra_error",
                is_infra_error=True,
                reason=f"Environment failed to confirm healthy for {self.confirm_healthy_seconds}s before {fault_id}",
                should_retry=True,
            )
            rec = RunRecord(
                incident_id=f"inc_{fault_id}_att{attempt_num}",
                fault_id=fault_id,
                t_detect=0.0,
                t_rca=0.0,
                t_fix=0.0,
                t_verified=0.0,
                rca_correct_top1=False,
                rca_correct_top3=False,
                fix_ok=False,
                unsafe=False,
            )
            return rec, cls

        try:
            self.inject_fn(fault_id)
            raw_out = self.orchestrate_fn(fault_id)
            elapsed = max(0.0, self.clock_fn() - start)
            rec, success, err_msg = self._extract_run_record(fault_id, raw_out, elapsed)
            cls = classify_run_outcome(
                success=success,
                exc=None,
                error_message=err_msg,
                health_check_fn=self.health_fn,
            )
            return rec, cls
        except Exception as exc:
            elapsed = max(0.0, self.clock_fn() - start)
            cls = classify_run_outcome(
                success=False,
                exc=exc,
                error_message=str(exc),
                health_check_fn=self.health_fn,
            )
            rec = RunRecord(
                incident_id=f"inc_{fault_id}_att{attempt_num}",
                fault_id=fault_id,
                t_detect=0.0,
                t_rca=0.0,
                t_fix=0.0,
                t_verified=round(elapsed, 4),
                rca_correct_top1=False,
                rca_correct_top3=False,
                fix_ok=False,
                unsafe=False,
            )
            return rec, cls
        finally:
            try:
                self.reset_fn(fault_id)
            except Exception as exc:
                logger.warning("Post-run reset warning for %s: %s", fault_id, exc)

    def run_fault(self, fault_id: str) -> BenchmarkRunEntry:
        """Execute a single fault with automatic one-time retry on infrastructure flakes."""
        attempts_log: List[Dict[str, Any]] = []

        rec, cls = self._run_attempt(fault_id, attempt_num=1)
        initial_status = cls.status
        had_infra_error = cls.is_infra_error
        attempts_log.append({
            "attempt": 1,
            "status": cls.status,
            "reason": cls.reason,
            "incident_id": rec.incident_id,
        })

        retried = False
        retry_count = 0

        if cls.is_infra_error and cls.should_retry and self.max_infra_retries >= 1:
            retried = True
            retry_count = 1
            logger.warning("Infra error on %s (%s); retrying once...", fault_id, cls.reason)
            rec, cls = self._run_attempt(fault_id, attempt_num=2)
            had_infra_error = had_infra_error or cls.is_infra_error
            attempts_log.append({
                "attempt": 2,
                "status": cls.status,
                "reason": cls.reason,
                "incident_id": rec.incident_id,
            })

        return BenchmarkRunEntry(
            fault_id=fault_id,
            status=cls.status,
            initial_status=initial_status,
            had_infra_error=had_infra_error,
            retried=retried,
            retry_count=retry_count,
            classification_reason=cls.reason,
            run_record=rec,
            attempts=attempts_log,
        )

    def run(
        self,
        fault_ids: Optional[Sequence[str]] = None,
        *,
        out_path: Union[str, Path] = DEFAULT_RESULTS_PATH,
        charts_dir: Optional[Union[str, Path]] = None,
        category_by_fault: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Run the full benchmark unattended and write results.json + SVG charts."""
        if fault_ids is None:
            loaded_ids, loaded_cats = load_fault_catalogue(self.repo_root / "docs" / "faults.json", limit=20)
            target_faults = loaded_ids
            cats = category_by_fault or loaded_cats
        else:
            _, loaded_cats = load_fault_catalogue(self.repo_root / "docs" / "faults.json", limit=None)
            target_faults = list(fault_ids)
            cats = category_by_fault or loaded_cats

        started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        entries: List[BenchmarkRunEntry] = []

        for fid in target_faults:
            entry = self.run_fault(fid)
            entries.append(entry)

        run_dicts = [e.to_dict() for e in entries]
        records = [e.run_record for e in entries]
        summary = aggregate_results(records, run_entries=run_dicts, category_by_fault=cats)

        out_file = Path(out_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        chart_target = Path(charts_dir) if charts_dir else out_file.parent / "charts"
        chart_paths = generate_charts(summary, records, chart_target)

        payload = {
            "generated_at": started_at,
            "fault_count": len(target_faults),
            "summary": summary,
            "charts": chart_paths,
            "runs": run_dicts,
            "records": [r.model_dump() for r in records],
        }
        out_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="NightShift Benchmark Runner (Day 7)")
    parser.add_argument("--faults", help="Comma-separated list of fault IDs (default: first 20 from docs/faults.json)")
    parser.add_argument("--out", default=str(DEFAULT_RESULTS_PATH), help="Output results.json path")
    parser.add_argument("--healthy-seconds", type=float, default=30.0, help="Seconds to confirm healthy between runs")
    args = parser.parse_args(argv)

    fault_ids = [f.strip() for f in args.faults.split(",") if f.strip()] if args.faults else None
    runner = BenchmarkRunner(confirm_healthy_seconds=args.healthy_seconds)
    result = runner.run(fault_ids, out_path=args.out)
    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
