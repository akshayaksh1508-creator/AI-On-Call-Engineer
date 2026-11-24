"""Automatic Rollback Guard (Day 5 Task A3).

Monitors service health post-promotion. If production metrics are worse
than baseline within 60 seconds, immediately triggers an automatic rollback
and logs the exact stated reason.

Owner: Person A.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional


logger = logging.getLogger("nightshift.verifier.rollback")

DEFAULT_ROLLBACK_WINDOW_SECONDS: float = 60.0  # Decides and rolls back within 60s
DEFAULT_POLL_INTERVAL_SECONDS: float = 1.0
DEFAULT_BAD_SAMPLES_THRESHOLD: int = 2  # Confirm degradation across consecutive samples


@dataclass(frozen=True)
class RollbackDecision:
    rolled_back: bool
    service: str
    baseline_error_rate: float
    observed_error_rate: float
    decision_time_seconds: float
    reason: str
    rollback_receipt: Optional[dict[str, Any]] = None


class AutoRollbackGuard:
    """Guards production promotions by enforcing an automatic 60s rollback deadline upon degradation."""

    def __init__(
        self,
        service: str,
        baseline_error_rate: float,
        *,
        rollback_fn: Optional[Callable[[str, str], Any]] = None,
        release_manager: Optional[Any] = None,
        window_seconds: float = DEFAULT_ROLLBACK_WINDOW_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        bad_samples_threshold: int = DEFAULT_BAD_SAMPLES_THRESHOLD,
        max_allowed_degradation: float = 0.0,
        time_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if not service:
            raise ValueError("service must not be empty")
        if window_seconds <= 0 or window_seconds > 60.0:
            raise ValueError(f"window_seconds must be between 1 and 60 seconds, got {window_seconds}")
        if bad_samples_threshold < 1:
            raise ValueError("bad_samples_threshold must be at least 1")

        self.service = service
        self.baseline_error_rate = baseline_error_rate
        self.window_seconds = window_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.bad_samples_threshold = bad_samples_threshold
        self.max_allowed_degradation = max_allowed_degradation
        self.time_fn = time_fn
        self.sleep_fn = sleep_fn

        # Resolve rollback execution handler
        if rollback_fn is not None:
            self._rollback_fn = rollback_fn
        elif release_manager is not None:
            self._rollback_fn = lambda svc, msg: release_manager.rollback(
                service=svc, author="auto-rollback-guard", message=msg
            )
        else:
            self._rollback_fn = lambda svc, msg: {"service": svc, "action": "mock_rollback", "message": msg}

    def is_degraded(self, current_error_rate: float) -> bool:
        """Return True if current metric is strictly worse than baseline by more than allowed margin."""
        threshold = round(self.baseline_error_rate + self.max_allowed_degradation, 4)
        return round(current_error_rate, 4) > threshold

    def execute_rollback(self, reason: str, observed_rate: float, elapsed: float) -> RollbackDecision:
        """Execute the configured rollback handler and log the exact reason."""
        logger.warning(
            "AUTOMATIC ROLLBACK TRIGGERED for service '%s' within %.2fs: %s",
            self.service,
            elapsed,
            reason,
        )
        receipt = None
        try:
            receipt = self._rollback_fn(self.service, reason)
        except Exception as exc:
            logger.error("Failed executing rollback for service '%s': %s", self.service, exc)
            receipt = {"error": str(exc), "status": "failed"}

        return RollbackDecision(
            rolled_back=True,
            service=self.service,
            baseline_error_rate=self.baseline_error_rate,
            observed_error_rate=observed_rate,
            decision_time_seconds=round(elapsed, 2),
            reason=reason,
            rollback_receipt=receipt,
        )

    def monitor(
        self,
        metric_sampler: Callable[[], float],
        *,
        timeout: Optional[float] = None,
    ) -> RollbackDecision:
        """Monitor post-promotion metrics for up to 60s. Roll back immediately if worse."""
        window = timeout if timeout is not None else self.window_seconds
        start_time = self.time_fn()
        deadline = start_time + window

        bad_samples_count = 0
        last_observed_rate = self.baseline_error_rate

        while self.time_fn() <= deadline:
            now = self.time_fn()
            elapsed = now - start_time

            try:
                current_rate = float(metric_sampler())
            except Exception as exc:
                logger.warning("Metric sampler error during rollback guard check: %s", exc)
                current_rate = self.baseline_error_rate + 0.05  # Treat error as degraded

            last_observed_rate = current_rate

            if self.is_degraded(current_rate):
                bad_samples_count += 1
                if bad_samples_count >= self.bad_samples_threshold:
                    reason = (
                        f"Post-promotion error rate ({current_rate:.2%}) is worse than baseline "
                        f"({self.baseline_error_rate:.2%}); automatic rollback executed in {elapsed:.1f}s (limit: 60s)"
                    )
                    return self.execute_rollback(reason, current_rate, elapsed)
            else:
                bad_samples_count = 0

            self.sleep_fn(self.poll_interval_seconds)

        elapsed_total = self.time_fn() - start_time
        reason = (
            f"Promotion safe: post-promotion error rate ({last_observed_rate:.2%}) "
            f"did not worsen over baseline ({self.baseline_error_rate:.2%}) during {elapsed_total:.1f}s guard window"
        )
        logger.info(
            "Promotion healthy for service '%s' over %.1fs window: %s",
            self.service,
            elapsed_total,
            reason,
        )
        return RollbackDecision(
            rolled_back=False,
            service=self.service,
            baseline_error_rate=self.baseline_error_rate,
            observed_error_rate=last_observed_rate,
            decision_time_seconds=round(elapsed_total, 2),
            reason=reason,
            rollback_receipt=None,
        )
