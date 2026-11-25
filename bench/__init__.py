"""bench component package.
Owner: Person A (Systems & Proof)
"""

from bench.aggregator import aggregate_results, generate_charts, load_results_and_aggregate
from bench.flake_handler import FlakeClassification, InfraError, ServiceKilledError, classify_run_outcome
from bench.runner import BenchmarkRunEntry, BenchmarkRunner, load_fault_catalogue
from bench.stage_timer import StageTimeline, StageTimer

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
]
