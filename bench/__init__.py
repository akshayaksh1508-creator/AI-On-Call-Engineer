"""bench component package.
Owner: Person A (Systems & Proof)
"""

from bench.ablations import AblationConfig, default_ablation_orchestrate, run_ablation_suite
from bench.aggregator import aggregate_results, generate_charts, load_results_and_aggregate
from bench.flake_handler import FlakeClassification, InfraError, ServiceKilledError, classify_run_outcome
from bench.human_baseline import (
    HumanBaselineEntry,
    create_default_human_baseline,
    validate_timer_sheet,
    write_human_baseline_artifacts,
)
from bench.regression import RegressionReport, RegressionSuite, extract_passing_faults
from bench.runner import BenchmarkRunEntry, BenchmarkRunner, load_fault_catalogue
from bench.stage_timer import StageTimeline, StageTimer
from bench.triage import TriagedFailure, VALID_TRIAGE_LABELS, build_triage_sheet, write_triage_artifacts
from bench.v1_runner import get_training_fault_ids, run_benchmark_v1

__all__ = [
    "StageTimer",
    "StageTimeline",
    "BenchmarkRunner",
    "BenchmarkRunEntry",
    "load_fault_catalogue",
    "aggregate_results",
    "generate_charts",
    "load_results_and_aggregate",
    "FlakeClassification",
    "InfraError",
    "ServiceKilledError",
    "classify_run_outcome",
    "get_training_fault_ids",
    "run_benchmark_v1",
    "TriagedFailure",
    "VALID_TRIAGE_LABELS",
    "build_triage_sheet",
    "write_triage_artifacts",
    "RegressionReport",
    "RegressionSuite",
    "extract_passing_faults",
    "AblationConfig",
    "default_ablation_orchestrate",
    "run_ablation_suite",
    "HumanBaselineEntry",
    "create_default_human_baseline",
    "validate_timer_sheet",
    "write_human_baseline_artifacts",
]
