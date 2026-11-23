"""Prometheus Telemetry Scraper and Threshold Evaluator.

Owner: Person A (Systems & Proof)
Monitors error rates and latency distributions against strict thresholds:
1. Error rate > 5% sustained for >= 30 seconds
2. p95 latency > 3x baseline sustained for >= 30 seconds
Supports live Prometheus PromQL query API, direct microservice /metrics scraping,
and offline metric sample feeds for automated testing.
"""

from dataclasses import dataclass, field
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request

logger = logging.getLogger("detector.evaluator")


@dataclass
class MetricObservation:
    """A point-in-time telemetry snapshot for a microservice."""
    timestamp: float
    total_requests: float
    errors_5xx: float
    duration_sum: float = 0.0
    duration_count: float = 0.0
    histogram_buckets: Dict[float, float] = field(default_factory=dict)
    p95_latency: float = 0.0


@dataclass
class EvaluationResult:
    """Result of threshold evaluation for a service at a point in time."""
    service: str
    timestamp: float
    is_anomalous: bool
    error_rate: float
    p95_latency: float
    alerts: List[str] = field(default_factory=list)
    symptoms: List[str] = field(default_factory=list)
    sustained_seconds: float = 0.0


class ServiceTelemetryEvaluator:
    """Evaluates telemetry time-series against error-rate and latency thresholds for a single service."""

    def __init__(
        self,
        service: str,
        error_rate_threshold: float = 0.05,      # 5% error rate
        latency_multiplier_threshold: float = 3.0, # 3x baseline
        baseline_p95_latency: float = 0.05,       # 50ms default baseline
        sustained_window_seconds: float = 30.0,   # 30 seconds persistence requirement
        min_requests_for_eval: int = 5,           # Avoid dividing by near-zero during cold start
    ):
        self.service = service
        self.error_rate_threshold = error_rate_threshold
        self.latency_multiplier_threshold = latency_multiplier_threshold
        self.baseline_p95_latency = baseline_p95_latency
        self.sustained_window_seconds = sustained_window_seconds
        self.min_requests_for_eval = min_requests_for_eval

        # History of metric observations: List of MetricObservation
        self.history: List[MetricObservation] = []
        # Timestamp when an anomaly condition first became true
        self._anomaly_first_seen: Optional[float] = None
        # Timestamp of the previous observation to detect gaps
        self._last_obs_timestamp: Optional[float] = None

    def reset(self) -> None:
        """Reset historical observations and anomaly timer."""
        self.history.clear()
        self._anomaly_first_seen = None
        self._last_obs_timestamp = None

    def add_observation(self, obs: MetricObservation) -> EvaluationResult:
        """Record a new metric observation and evaluate thresholds."""
        data_gap = (obs.timestamp - self._last_obs_timestamp) if self._last_obs_timestamp is not None else None
        self._last_obs_timestamp = obs.timestamp

        self.history.append(obs)
        # Keep up to 10 minutes of history
        cutoff = obs.timestamp - 600.0
        self.history = [o for o in self.history if o.timestamp >= cutoff]

        return self.evaluate_current(now=obs.timestamp, data_gap=data_gap)

    def evaluate_current(self, now: Optional[float] = None, data_gap: Optional[float] = None) -> EvaluationResult:
        """Evaluate whether current metrics violate sustained thresholds over the last sustained_window_seconds."""
        if not self.history:
            return EvaluationResult(
                service=self.service,
                timestamp=now or time.time(),
                is_anomalous=False,
                error_rate=0.0,
                p95_latency=0.0,
            )

        current = self.history[-1]
        eval_time = now or current.timestamp

        # Find observation at start of window (approximately sustained_window_seconds ago)
        window_start_time = eval_time - self.sustained_window_seconds
        past_candidates = [o for o in self.history if o.timestamp <= window_start_time]
        past = past_candidates[-1] if past_candidates else self.history[0]

        # Calculate delta over the window
        delta_requests = max(0.0, current.total_requests - past.total_requests)
        delta_errors = max(0.0, current.errors_5xx - past.errors_5xx)

        # Fallback to current snapshot totals if counters were reset or single observation
        if delta_requests == 0.0 and current.total_requests > 0:
            delta_requests = current.total_requests
            delta_errors = current.errors_5xx

        # Calculate error rate
        error_rate = (delta_errors / delta_requests) if delta_requests >= self.min_requests_for_eval else 0.0

        # Calculate p95 latency
        p95_latency = current.p95_latency
        if p95_latency == 0.0 and current.histogram_buckets:
            p95_latency = self._compute_p95_from_buckets(current.histogram_buckets, current.duration_count)

        # Evaluate individual threshold conditions
        error_condition = error_rate >= self.error_rate_threshold
        latency_threshold = self.baseline_p95_latency * self.latency_multiplier_threshold
        latency_condition = p95_latency >= latency_threshold

        alerts: List[str] = []
        symptoms: List[str] = []

        if error_condition:
            alerts.append(f"{self.service.capitalize()}High5xxRate")
            symptoms.append(
                f"HTTP 5xx error rate is {error_rate:.1%} (exceeds threshold of {self.error_rate_threshold:.1%})"
            )

        if latency_condition:
            alerts.append(f"{self.service.capitalize()}LatencySpike")
            symptoms.append(
                f"p95 latency is {p95_latency * 1000:.1f}ms (exceeds 3x baseline threshold of {latency_threshold * 1000:.1f}ms)"
            )

        # Check sustained condition (must persist for >= sustained_window_seconds)
        is_failing_now = bool(alerts)
        sustained_duration = 0.0

        if is_failing_now:
            # If this is the first failure, or if there was a data gap > 1.5x sustained_window, reset streak
            if (
                self._anomaly_first_seen is None
                or data_gap is None
                or data_gap > (self.sustained_window_seconds * 1.5)
            ):
                self._anomaly_first_seen = eval_time
            sustained_duration = eval_time - self._anomaly_first_seen
        else:
            # Metrics are healthy; reset sustained timer
            self._anomaly_first_seen = None

        # Sustained threshold met if duration >= window, or if past window also showed failure
        is_sustained = (sustained_duration >= self.sustained_window_seconds)

        return EvaluationResult(
            service=self.service,
            timestamp=eval_time,
            is_anomalous=is_sustained,
            error_rate=error_rate,
            p95_latency=p95_latency,
            alerts=alerts if is_sustained else [],
            symptoms=symptoms if is_sustained else [],
            sustained_seconds=sustained_duration,
        )

    def _compute_p95_from_buckets(self, buckets: Dict[float, float], total_count: float) -> float:
        """Estimate p95 latency via linear interpolation over histogram buckets."""
        if total_count <= 0 or not buckets:
            return 0.0
        target_count = 0.95 * total_count

        sorted_buckets = sorted(buckets.items(), key=lambda b: b[0])
        prev_bound = 0.0
        prev_count = 0.0

        for bound, count in sorted_buckets:
            if count >= target_count:
                # Linear interpolation within this bucket
                bucket_count = count - prev_count
                if bucket_count <= 0:
                    return bound
                fraction = (target_count - prev_count) / bucket_count
                return prev_bound + fraction * (bound - prev_bound)
            prev_bound = bound
            prev_count = count

        return sorted_buckets[-1][0] if sorted_buckets else 0.0


def parse_prometheus_text(text: str, service: str) -> MetricObservation:
    """Parse Prometheus text exposition format into a MetricObservation."""
    total_requests = 0.0
    errors_5xx = 0.0
    duration_sum = 0.0
    duration_count = 0.0
    buckets: Dict[float, float] = {}

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # http_requests_total{service="...", endpoint="...", method="...", status="500"} 12.0
        if line.startswith("http_requests_total"):
            match = re.search(r'status="(\d+)"[^}]*\}\s+([\d\.e\+\-]+)', line)
            if match:
                status_code = int(match.group(1))
                val = float(match.group(2))
                total_requests += val
                if status_code >= 500:
                    errors_5xx += val

        # http_errors_total{service="...", endpoint="...", status_code="500"} 12.0
        elif line.startswith("http_errors_total"):
            match = re.search(r'status_code="(\d+)"[^}]*\}\s+([\d\.e\+\-]+)', line)
            if match:
                status_code = int(match.group(1))
                val = float(match.group(2))
                if status_code >= 500 and errors_5xx == 0.0:
                    errors_5xx += val

        # http_request_duration_seconds_bucket{le="0.05", ...} 45.0
        elif "http_request_duration_seconds_bucket" in line:
            match = re.search(r'le="([\d\.e\+\-]+|\+Inf)"[^}]*\}\s+([\d\.e\+\-]+)', line)
            if match:
                le_str = match.group(1)
                val = float(match.group(2))
                if le_str != "+Inf":
                    buckets[float(le_str)] = val

        # http_request_duration_seconds_count 50.0
        elif "http_request_duration_seconds_count" in line:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    duration_count = float(parts[-1])
                except ValueError:
                    pass

        # http_request_duration_seconds_sum 1.25
        elif "http_request_duration_seconds_sum" in line:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    duration_sum = float(parts[-1])
                except ValueError:
                    pass

    return MetricObservation(
        timestamp=time.time(),
        total_requests=total_requests,
        errors_5xx=errors_5xx,
        duration_sum=duration_sum,
        duration_count=duration_count,
        histogram_buckets=buckets,
    )
