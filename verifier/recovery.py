"""Production Recovery Checker (Day 5 Task A2).

Watches production metrics after fix promotion until error rate remains strictly
under 1% (< 0.01) continuously for 60 seconds, recording the exact `recovered_at`
ISO 8601 timestamp.

Owner: Person A.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Optional, Sequence


DEFAULT_TARGET_ERROR_RATE: float = 0.01  # Under 1%
DEFAULT_REQUIRED_STABLE_SECONDS: float = 60.0  # 60s sustained stability window
DEFAULT_WATCH_TIMEOUT_SECONDS: float = 300.0  # Max wait time (5 minutes)
DEFAULT_POLL_INTERVAL_SECONDS: float = 1.0  # Polling cadence


class RecoveryState(str, Enum):
    MONITORING = "MONITORING"
    STABILIZING = "STABILIZING"
    RECOVERED = "RECOVERED"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class MetricSample:
    timestamp: float
    error_rate: float


@dataclass(frozen=True)
class RecoveryResult:
    recovered: bool
    recovered_at: Optional[str]  # ISO 8601 UTC timestamp of recovery
    confirmed_at: Optional[str]  # ISO 8601 UTC timestamp when 60s stability window completed
    stable_duration_seconds: float
    final_error_rate: float
    samples_count: int
    history: Sequence[MetricSample] = field(default_factory=tuple)
    reason: str = ""


class ProductionRecoveryChecker:
    """Monitors production metrics after fix promotion until sustained health is proven."""

    def __init__(
        self,
        *,
        target_error_rate: float = DEFAULT_TARGET_ERROR_RATE,
        required_stable_seconds: float = DEFAULT_REQUIRED_STABLE_SECONDS,
        timeout_seconds: float = DEFAULT_WATCH_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        time_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if target_error_rate <= 0:
            raise ValueError("target_error_rate must be positive")
        if required_stable_seconds <= 0:
            raise ValueError("required_stable_seconds must be positive")
        if timeout_seconds < required_stable_seconds:
            raise ValueError("timeout_seconds cannot be less than required_stable_seconds")

        self.target_error_rate = target_error_rate
        self.required_stable_seconds = required_stable_seconds
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.time_fn = time_fn
        self.sleep_fn = sleep_fn

        # Internal state tracking
        self.state = RecoveryState.MONITORING
        self.stable_start_time: Optional[float] = None
        self.history: list[MetricSample] = []

    def reset(self) -> None:
        """Reset internal watcher state."""
        self.state = RecoveryState.MONITORING
        self.stable_start_time = None
        self.history.clear()

    def process_sample(self, error_rate: float, now: Optional[float] = None) -> RecoveryState:
        """Feed a single error-rate reading and advance state machine."""
        t = now if now is not None else self.time_fn()
        self.history.append(MetricSample(timestamp=t, error_rate=error_rate))

        if self.state == RecoveryState.RECOVERED:
            return self.state

        if error_rate < self.target_error_rate:
            if self.stable_start_time is None:
                self.stable_start_time = t
                self.state = RecoveryState.STABILIZING

            stable_duration = t - self.stable_start_time
            if stable_duration >= self.required_stable_seconds:
                self.state = RecoveryState.RECOVERED
        else:
            # Metric spiked above 1% -> reset stabilization timer
            self.stable_start_time = None
            self.state = RecoveryState.MONITORING

        return self.state

    def watch(
        self,
        metric_sampler: Callable[[], float],
        *,
        timeout: Optional[float] = None,
        required_stable_seconds: Optional[float] = None,
    ) -> RecoveryResult:
        """Poll metric_sampler in real-time until error rate is <1% for required_stable_seconds."""
        self.reset()
        req_seconds = required_stable_seconds if required_stable_seconds is not None else self.required_stable_seconds
        max_wait = timeout if timeout is not None else self.timeout_seconds

        start_time = self.time_fn()
        deadline = start_time + max_wait

        last_error_rate = 1.0

        while self.time_fn() <= deadline:
            now = self.time_fn()
            try:
                last_error_rate = float(metric_sampler())
            except Exception as exc:
                # Sampler error treated as unhealthy reading (1.0 error rate)
                last_error_rate = 1.0

            state = self.process_sample(last_error_rate, now=now)
            if state == RecoveryState.RECOVERED and self.stable_start_time is not None:
                recovered_dt = datetime.fromtimestamp(self.stable_start_time, tz=timezone.utc)
                confirmed_dt = datetime.fromtimestamp(now, tz=timezone.utc)
                duration = round(now - self.stable_start_time, 2)
                return RecoveryResult(
                    recovered=True,
                    recovered_at=recovered_dt.isoformat(),
                    confirmed_at=confirmed_dt.isoformat(),
                    stable_duration_seconds=duration,
                    final_error_rate=last_error_rate,
                    samples_count=len(self.history),
                    history=tuple(self.history),
                    reason=f"Error rate stabilized at {last_error_rate:.2%} (< {self.target_error_rate:.2%}) for {duration}s",
                )

            self.sleep_fn(self.poll_interval_seconds)

        # Timed out without achieving required stable window
        self.state = RecoveryState.TIMEOUT
        return RecoveryResult(
            recovered=False,
            recovered_at=None,
            confirmed_at=None,
            stable_duration_seconds=0.0,
            final_error_rate=last_error_rate,
            samples_count=len(self.history),
            history=tuple(self.history),
            reason=f"Timeout of {max_wait}s exceeded without sustaining error rate < {self.target_error_rate:.2%} for {req_seconds}s",
        )
