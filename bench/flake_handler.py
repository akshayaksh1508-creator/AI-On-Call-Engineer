"""Infrastructure Flake Classification & Retry Policy (Day 7 Task A4).

Separates transient infrastructure failures (e.g. a killed service/container,
broken pipe, connection refused, OOM/SIGKILL, harness timeout) from genuine
agent/verification failures (`fail`), and coordinates a single automatic retry.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

logger = logging.getLogger("nightshift.bench.flake_handler")

RunStatus = Literal["pass", "fail", "infra_error"]

INFRA_ERROR_KEYWORDS = (
    "connection refused",
    "connection reset",
    "broken pipe",
    "service killed",
    "container exited",
    "sigkill",
    "process killed",
    "infra_error",
    "docker daemon",
    "name or service not known",
    "temporarily unavailable",
    "502 bad gateway",
    "503 service unavailable",
    "cannot connect to",
)


class InfraError(RuntimeError):
    """Raised when an underlying infrastructure dependency fails mid-run."""


class ServiceKilledError(InfraError):
    """Raised when a target or platform service process is killed mid-run."""


@dataclass
class FlakeClassification:
    """Result of classifying an incident run outcome."""

    status: RunStatus
    is_infra_error: bool
    reason: str
    should_retry: bool = False


def classify_run_outcome(
    *,
    success: bool,
    exc: Optional[BaseException] = None,
    error_message: Optional[str] = None,
    health_check_fn: Optional[Callable[[], bool]] = None,
) -> FlakeClassification:
    """Classify a benchmark run outcome into 'pass', 'fail', or 'infra_error'."""
    if success and exc is None:
        return FlakeClassification(
            status="pass",
            is_infra_error=False,
            reason="Remediation verified successfully",
            should_retry=False,
        )

    # 1. Explicit infrastructure exception types
    if isinstance(exc, (InfraError, ConnectionError, BrokenPipeError)):
        return FlakeClassification(
            status="infra_error",
            is_infra_error=True,
            reason=f"Infrastructure exception ({type(exc).__name__}): {exc}",
            should_retry=True,
        )

    # 2. Keyword inspection on exception or error message
    combined_msg = " ".join(
        part for part in (str(exc) if exc else "", error_message or "") if part
    ).lower()
    for kw in INFRA_ERROR_KEYWORDS:
        if kw in combined_msg:
            return FlakeClassification(
                status="infra_error",
                is_infra_error=True,
                reason=f"Detected infrastructure failure signature ('{kw}'): {combined_msg[:200]}",
                should_retry=True,
            )

    # 3. Probe service health if an exception occurred mid-run
    if exc is not None and health_check_fn is not None:
        try:
            if not health_check_fn():
                return FlakeClassification(
                    status="infra_error",
                    is_infra_error=True,
                    reason=f"Service became unreachable/unhealthy mid-run after exception: {exc}",
                    should_retry=True,
                )
        except Exception as health_exc:
            return FlakeClassification(
                status="infra_error",
                is_infra_error=True,
                reason=f"Health probe failed mid-run ({health_exc}) after exception: {exc}",
                should_retry=True,
            )

    # 4. Otherwise it is an agent/verification failure
    detail = str(exc) if exc else (error_message or "Verification or RCA failed")
    return FlakeClassification(
        status="fail",
        is_infra_error=False,
        reason=detail,
        should_retry=False,
    )
