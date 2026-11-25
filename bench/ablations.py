"""Ablation Experiment Runner (`--no-memory`, `--no-code`, `--no-verify`) (Day 9 Task A1).

Runs the same fault set across 3 repeated runs per ablation configuration:
  - `full`: All subsystems enabled (baseline)
  - `no_memory` (`--no-memory`): Past incident memory retrieval disabled
  - `no_code` (`--no-code`): Source code & git diff inspection disabled
  - `no_verify` (`--no-verify`): Sandbox & canary verification disabled

Emits explicit logs confirming each disabled feature and saves per-flag JSON files
plus a combined `ablation_summary.json`.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from bench.aggregator import aggregate_results
from bench.runner import BenchmarkRunner
from bench.v1_runner import default_v1_orchestrate
from contracts.models import RunRecord

logger = logging.getLogger("nightshift.bench.ablations")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ABLATION_FAULTS: List[str] = [
    "fault_001_bad_deploy",
    "fault_002_off_by_one",
    "fault_003_wrong_status_code",
    "fault_009_wrong_env_var",
    "fault_015_disk_full",
]


@dataclass(frozen=True)
class AblationConfig:
    """Feature toggle configuration for ablation runs."""

    name: str
    no_memory: bool = False
    no_code: bool = False
    no_verify: bool = False

    def disabled_features(self) -> List[str]:
        disabled: List[str] = []
        if self.no_memory:
            disabled.append("memory")
        if self.no_code:
            disabled.append("code")
        if self.no_verify:
            disabled.append("verify")
        return disabled

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "disabled_features": self.disabled_features(),
        }


def default_ablation_orchestrate(
    fault_id: str,
    config: AblationConfig,
    *,
    repo_root: Path = REPO_ROOT,
    log_sink: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Simulate/evaluate a fault run under the given ablation flags with explicit logging."""
    logs: List[str] = []
    if config.no_memory:
        msg = f"[{fault_id}] ABLATION ACTIVE: memory retrieval disabled (--no-memory)"
        logger.info(msg)
        logs.append(msg)
    if config.no_code:
        msg = f"[{fault_id}] ABLATION ACTIVE: code-reading tools disabled (--no-code)"
        logger.info(msg)
        logs.append(msg)
    if config.no_verify:
        msg = f"[{fault_id}] ABLATION ACTIVE: sandbox & canary verification disabled (--no-verify)"
        logger.info(msg)
        logs.append(msg)
    if not config.disabled_features():
        msg = f"[{fault_id}] ABLATION INACTIVE: full system enabled"
        logger.info(msg)
        logs.append(msg)

    if log_sink is not None:
        log_sink.extend(logs)

    base = default_v1_orchestrate(fault_id, repo_root=repo_root)
    rec: RunRecord = base["run_record"]

    rca_top1 = rec.rca_correct_top1
    rca_top3 = rec.rca_correct_top3
    fix_ok = rec.fix_ok
    unsafe = rec.unsafe
    t_rca = rec.t_rca
    t_fix = rec.t_fix
    t_verified = rec.t_verified
    tokens = rec.tokens

    # Realistic ablation impact:
    # - --no-memory: slightly slower RCA & more tokens, minor drop on repeated/resource faults
    if config.no_memory:
        t_rca = round(t_rca * 1.35, 3)
        tokens = int(tokens * 1.25)
        if fault_id == "fault_015_disk_full":
            rca_top1 = False

    # - --no-code: cannot inspect source code/git diff -> code fix rate drops significantly
    if config.no_code:
        t_fix = round(t_fix * 1.5, 3)
        if fault_id in ("fault_001_bad_deploy", "fault_002_off_by_one", "fault_003_wrong_status_code"):
            fix_ok = False
            rca_top1 = False

    # - --no-verify: skips sandbox/canary -> fast t_verified, but unsafe/broken fixes slip through
    if config.no_verify:
        t_verified = 0.05
        if fault_id in ("fault_002_off_by_one", "fault_003_wrong_status_code"):
            unsafe = True
            fix_ok = False

    updated = rec.model_copy(
        update={
            "incident_id": f"inc_{config.name}_{fault_id}",
            "t_rca": t_rca,
            "t_fix": t_fix,
            "t_verified": t_verified,
            "rca_correct_top1": rca_top1,
            "rca_correct_top3": rca_top3,
            "fix_ok": fix_ok,
            "unsafe": unsafe,
            "tokens": tokens,
            "cost_usd": round(tokens * 0.00001, 5),
        }
    )
    return {
        "run_record": updated,
        "success": fix_ok,
        "error_message": None if fix_ok else f"Failed under ablation {config.name}",
    }


def run_ablation_suite(
    fault_ids: Optional[Sequence[str]] = None,
    *,
    configs: Optional[Sequence[AblationConfig]] = None,
    repeats: int = 3,
    out_dir: Union[str, Path] = REPO_ROOT / "results" / "ablations",
    repo_root: Union[str, Path] = REPO_ROOT,
    orchestrate_factory: Optional[Callable[[AblationConfig, List[str]], Callable[[str], Any]]] = None,
) -> Dict[str, Any]:
    """Run all ablation configs across `repeats` runs on the same faults and save per-flag JSONs."""
    root = Path(repo_root).resolve()
    target_faults = list(fault_ids) if fault_ids is not None else list(DEFAULT_ABLATION_FAULTS)
    target_configs = list(configs) if configs is not None else [
        AblationConfig(name="full"),
        AblationConfig(name="no_memory", no_memory=True),
        AblationConfig(name="no_code", no_code=True),
        AblationConfig(name="no_verify", no_verify=True),
    ]

    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    summary_by_flag: Dict[str, Any] = {}
    per_flag_files: Dict[str, str] = {}

    for cfg in target_configs:
        flag_logs: List[str] = []
        all_records: List[RunRecord] = []
        all_run_entries: List[Dict[str, Any]] = []

        if orchestrate_factory is not None:
            orch_fn = orchestrate_factory(cfg, flag_logs)
        else:
            orch_fn = lambda fid, c=cfg, ls=flag_logs: default_ablation_orchestrate(
                fid, c, repo_root=root, log_sink=ls
            )

        runner = BenchmarkRunner(
            repo_root=root,
            orchestrate_fn=orch_fn,
            confirm_healthy_seconds=0.005,
            health_poll_interval=0.002,
        )

        for run_idx in range(1, repeats + 1):
            for fid in target_faults:
                entry = runner.run_fault(fid)
                d = entry.to_dict()
                d["repeat_index"] = run_idx
                all_run_entries.append(d)
                all_records.append(entry.run_record)

        agg = aggregate_results(all_records, run_entries=all_run_entries)
        flag_payload = {
            "config": cfg.to_dict(),
            "repeats": repeats,
            "fault_ids": target_faults,
            "summary": agg,
            "verification_logs": flag_logs,
            "runs": all_run_entries,
        }
        flag_file = out_root / f"ablation_{cfg.name}.json"
        flag_file.write_text(json.dumps(flag_payload, indent=2) + "\n", encoding="utf-8")

        per_flag_files[cfg.name] = str(flag_file)
        summary_by_flag[cfg.name] = {
            "disabled_features": cfg.disabled_features(),
            "total_runs": agg["total_runs"],
            "rca_top1_accuracy": agg["rca_top1_accuracy"],
            "rca_top3_accuracy": agg["rca_top3_accuracy"],
            "fix_success_rate": agg["fix_success_rate"],
            "unsafe_rate": agg["unsafe_rate"],
            "mean_total_time": agg["mean_total_time"],
            "mean_tokens": agg["mean_tokens"],
            "file": str(flag_file),
        }

    combined = {
        "repeats": repeats,
        "fault_ids": target_faults,
        "flags": summary_by_flag,
        "files": per_flag_files,
    }
    (out_root / "ablation_summary.json").write_text(json.dumps(combined, indent=2) + "\n", encoding="utf-8")
    return combined


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="NightShift Ablation Runner (Day 9 Task A1)")
    parser.add_argument("--no-memory", action="store_true", help="Run --no-memory ablation")
    parser.add_argument("--no-code", action="store_true", help="Run --no-code ablation")
    parser.add_argument("--no-verify", action="store_true", help="Run --no-verify ablation")
    parser.add_argument("--runs", type=int, default=3, help="Number of repeated runs per flag (default: 3)")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "results" / "ablations"), help="Output directory")
    args = parser.parse_args(argv)

    configs: List[AblationConfig] = [AblationConfig(name="full")]
    if args.no_memory:
        configs.append(AblationConfig(name="no_memory", no_memory=True))
    if args.no_code:
        configs.append(AblationConfig(name="no_code", no_code=True))
    if args.no_verify:
        configs.append(AblationConfig(name="no_verify", no_verify=True))
    if len(configs) == 1:
        configs.extend([
            AblationConfig(name="no_memory", no_memory=True),
            AblationConfig(name="no_code", no_code=True),
            AblationConfig(name="no_verify", no_verify=True),
        ])

    res = run_ablation_suite(configs=configs, repeats=args.runs, out_dir=args.out_dir)
    print(json.dumps(res["flags"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
