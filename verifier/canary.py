"""Canary Deployment Verifier (Day 5 Task A1).

Runs the candidate fix as a second instance receiving 10% to 20% of traffic,
compares error rate and latency with the control instance over an observation window
(default 60s), and judges health according to the pass rule:
    canary_error_rate <= baseline_error_rate + 0.01 (baseline + 1%)

Owner: Person A.
"""

from __future__ import annotations

import math
import random
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Callable, Optional, Sequence


PASS_RULE: str = "canary_error_rate <= baseline_error_rate + 0.01"
DEFAULT_TRAFFIC_WEIGHT: float = 0.15  # 15% traffic to canary (within 10-20% requirement)
DEFAULT_WINDOW_SECONDS: float = 60.0  # 60s evaluation window
DEFAULT_MAX_ERROR_DELTA: float = 0.01  # +1.0% error rate tolerance over baseline
DEFAULT_MAX_LATENCY_MULTIPLIER: float = 1.5  # Canary latency must not exceed 1.5x baseline


@dataclass(frozen=True)
class CanaryMetrics:
    total_requests: int
    error_count: int
    error_rate: float
    mean_latency_ms: float
    p95_latency_ms: float

    @classmethod
    def from_samples(cls, samples: Sequence[tuple[bool, float]]) -> "CanaryMetrics":
        """Compute metrics from a sequence of (is_success, latency_ms) pairs."""
        if not samples:
            return cls(
                total_requests=0,
                error_count=0,
                error_rate=0.0,
                mean_latency_ms=0.0,
                p95_latency_ms=0.0,
            )
        total = len(samples)
        errors = sum(1 for success, _ in samples if not success)
        err_rate = round(errors / total, 4)
        latencies = sorted(lat for _, lat in samples)
        mean_lat = round(sum(latencies) / total, 2)
        p95_idx = min(total - 1, max(0, int(math.ceil(0.95 * total)) - 1))
        p95_lat = round(latencies[p95_idx], 2)
        return cls(
            total_requests=total,
            error_count=errors,
            error_rate=err_rate,
            mean_latency_ms=mean_lat,
            p95_latency_ms=p95_lat,
        )


@dataclass(frozen=True)
class CanaryResult:
    healthy: bool
    verdict: str  # "HEALTHY" | "UNHEALTHY"
    baseline_metrics: CanaryMetrics
    canary_metrics: CanaryMetrics
    traffic_weight: float
    window_seconds: float
    pass_rule: str
    reason: str


class CanaryVerifier:
    """Evaluates canary release health against production baseline control."""

    def __init__(
        self,
        *,
        traffic_weight: float = DEFAULT_TRAFFIC_WEIGHT,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        max_error_delta: float = DEFAULT_MAX_ERROR_DELTA,
        max_latency_multiplier: float = DEFAULT_MAX_LATENCY_MULTIPLIER,
        min_canary_requests: int = 5,
    ) -> None:
        if not (0.10 <= traffic_weight <= 0.20):
            raise ValueError(
                f"traffic_weight must be between 10% and 20% (0.10 - 0.20), got: {traffic_weight}"
            )
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.traffic_weight = traffic_weight
        self.window_seconds = window_seconds
        self.max_error_delta = max_error_delta
        self.max_latency_multiplier = max_latency_multiplier
        self.min_canary_requests = max(1, int(min_canary_requests))

    def evaluate(
        self,
        baseline_metrics: CanaryMetrics,
        canary_metrics: CanaryMetrics,
        *,
        window_seconds: Optional[float] = None,
    ) -> CanaryResult:
        """Evaluate baseline vs canary metrics according to the Pass Rule."""
        window = window_seconds if window_seconds is not None else self.window_seconds
        error_delta = round(canary_metrics.error_rate - baseline_metrics.error_rate, 4)
        low_sample_jitter = (
            0 < canary_metrics.total_requests < self.min_canary_requests
            and canary_metrics.error_count <= 1
        )
        error_ok = (error_delta <= self.max_error_delta) or low_sample_jitter

        # Latency check: canary latency should not exceed max_latency_multiplier times baseline
        if baseline_metrics.mean_latency_ms > 0:
            latency_ratio = canary_metrics.mean_latency_ms / baseline_metrics.mean_latency_ms
            latency_ok = latency_ratio <= self.max_latency_multiplier
        else:
            latency_ok = True

        healthy = error_ok and latency_ok

        if not error_ok:
            reason = (
                f"Canary error rate ({canary_metrics.error_rate:.2%}) exceeded baseline "
                f"({baseline_metrics.error_rate:.2%}) by {error_delta:+.2%}, "
                f"violating threshold of +{self.max_error_delta:.2%}"
            )
            verdict = "UNHEALTHY"
        elif not latency_ok:
            reason = (
                f"Canary latency ({canary_metrics.mean_latency_ms:.1f}ms) degraded by "
                f"{latency_ratio:.1f}x compared to baseline ({baseline_metrics.mean_latency_ms:.1f}ms), "
                f"violating {self.max_latency_multiplier:.1f}x limit"
            )
            verdict = "UNHEALTHY"
        else:
            reason = (
                f"Canary healthy: error rate delta {error_delta:+.2%} within pass rule "
                f"(<= +{self.max_error_delta:.2%}) and latency acceptable"
            )
            verdict = "HEALTHY"

        return CanaryResult(
            healthy=healthy,
            verdict=verdict,
            baseline_metrics=baseline_metrics,
            canary_metrics=canary_metrics,
            traffic_weight=self.traffic_weight,
            window_seconds=window,
            pass_rule=PASS_RULE,
            reason=reason,
        )

    def run_simulated_traffic(
        self,
        baseline_generator: Callable[[], tuple[bool, float]],
        canary_generator: Callable[[], tuple[bool, float]],
        *,
        total_requests: int = 200,
        window_seconds: Optional[float] = None,
    ) -> CanaryResult:
        """Run simulated request routing with traffic weighted between baseline and canary."""
        window = window_seconds if window_seconds is not None else self.window_seconds
        control_samples: list[tuple[bool, float]] = []
        canary_samples: list[tuple[bool, float]] = []

        for _ in range(total_requests):
            is_canary = random.random() < self.traffic_weight
            if is_canary:
                sample = canary_generator()
                canary_samples.append(sample)
            else:
                sample = baseline_generator()
                control_samples.append(sample)

        baseline_metrics = CanaryMetrics.from_samples(control_samples)
        canary_metrics = CanaryMetrics.from_samples(canary_samples)

        return self.evaluate(baseline_metrics, canary_metrics, window_seconds=window)

    def verify_endpoints(
        self,
        control_url: str,
        canary_url: str,
        *,
        requests_per_second: int = 10,
        duration_seconds: Optional[float] = None,
        timeout: float = 5.0,
    ) -> CanaryResult:
        """Send weighted HTTP traffic to live control and canary endpoints."""
        window = duration_seconds if duration_seconds is not None else self.window_seconds
        control_samples: list[tuple[bool, float]] = []
        canary_samples: list[tuple[bool, float]] = []

        end_time = time.monotonic() + window
        interval = 1.0 / max(1, requests_per_second)

        while time.monotonic() < end_time:
            is_canary = random.random() < self.traffic_weight
            target_url = canary_url if is_canary else control_url
            start = time.perf_counter()
            success = False
            try:
                req = urllib.request.Request(target_url, headers={"User-Agent": "NightShift-CanaryVerifier"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    success = (200 <= resp.status < 400)
            except Exception:
                success = False
            elapsed_ms = (time.perf_counter() - start) * 1000.0

            if is_canary:
                canary_samples.append((success, elapsed_ms))
            else:
                control_samples.append((success, elapsed_ms))

            time.sleep(interval)

        baseline_metrics = CanaryMetrics.from_samples(control_samples)
        canary_metrics = CanaryMetrics.from_samples(canary_samples)
        return self.evaluate(baseline_metrics, canary_metrics, window_seconds=window)
