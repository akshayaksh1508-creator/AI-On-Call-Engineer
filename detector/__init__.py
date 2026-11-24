"""detector component package.

Owner: Person A (Systems & Proof)
Provides Prometheus telemetry polling, threshold evaluation, deduplication,
and autonomous Incident creation (Day 2 Task A1).
"""

from detector.evaluator import (
    EvaluationResult,
    MetricObservation,
    ServiceTelemetryEvaluator,
    parse_prometheus_text,
)
from detector.detector import IncidentDetector
from detector.trigger import DetectorTrigger, TriggerRun

__all__ = [
    "IncidentDetector",
    "ServiceTelemetryEvaluator",
    "MetricObservation",
    "EvaluationResult",
    "parse_prometheus_text",
    "DetectorTrigger",
    "TriggerRun",
]
