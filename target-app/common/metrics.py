"""Prometheus Metrics and Telemetry Middleware for NightShift Services.

Exposes:
- http_requests_total (service, endpoint, method, status)
- http_errors_total (service, endpoint, status_code)
- http_request_duration_seconds (service, endpoint)
"""

import time
import uuid
from typing import Callable
from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    CONTENT_TYPE_LATEST,
    generate_latest,
)

# Global custom registry to allow isolated per-service or unified collection
registry = CollectorRegistry()

REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests received",
    ["service", "endpoint", "method", "status"],
    registry=registry,
)

ERRORS_TOTAL = Counter(
    "http_errors_total",
    "Total HTTP errors encountered (status >= 400)",
    ["service", "endpoint", "status_code"],
    registry=registry,
)

REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["service", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=registry,
)


def add_telemetry_middleware(app: FastAPI, service_name: str, logger) -> None:
    """Attaches trace extraction, metrics recording, and structured logging middleware."""

    @app.middleware("http")
    async def telemetry_middleware(request: Request, call_next: Callable) -> Response:
        # Trace propagation: extract from incoming header or generate new trace_id
        trace_id = (
            request.headers.get("X-Trace-ID")
            or request.headers.get("x-trace-id")
            or str(uuid.uuid4())
        )
        request.state.trace_id = trace_id

        endpoint = request.url.path
        method = request.method
        start_time = time.time()

        # Log request start (skip noisy /health and /metrics polling logs for clarity, but track them if needed)
        if endpoint not in ("/health", "/metrics"):
            logger.info(
                f"Handling {method} {endpoint}",
                extra={"trace_id": trace_id, "extra_fields": {"path": endpoint, "method": method}},
            )

        try:
            response: Response = await call_next(request)
            duration = time.time() - start_time
            status_code = str(response.status_code)

            # Record Prometheus metrics
            REQUESTS_TOTAL.labels(
                service=service_name, endpoint=endpoint, method=method, status=status_code
            ).inc()
            REQUEST_DURATION_SECONDS.labels(
                service=service_name, endpoint=endpoint
            ).observe(duration)

            if response.status_code >= 400:
                ERRORS_TOTAL.labels(
                    service=service_name, endpoint=endpoint, status_code=status_code
                ).inc()
                logger.error(
                    f"{method} {endpoint} failed with status {status_code} in {duration:.4f}s",
                    extra={"trace_id": trace_id, "extra_fields": {"status": response.status_code}},
                )
            elif endpoint not in ("/health", "/metrics"):
                logger.info(
                    f"{method} {endpoint} completed with status {status_code} in {duration:.4f}s",
                    extra={"trace_id": trace_id, "extra_fields": {"status": response.status_code}},
                )

            # Propagate trace_id back in response headers
            response.headers["X-Trace-ID"] = trace_id
            return response

        except Exception as exc:
            duration = time.time() - start_time
            REQUESTS_TOTAL.labels(
                service=service_name, endpoint=endpoint, method=method, status="500"
            ).inc()
            ERRORS_TOTAL.labels(
                service=service_name, endpoint=endpoint, status_code="500"
            ).inc()
            REQUEST_DURATION_SECONDS.labels(
                service=service_name, endpoint=endpoint
            ).observe(duration)

            logger.exception(
                f"Unhandled error in {method} {endpoint}: {exc}",
                extra={"trace_id": trace_id},
            )
            raise exc


def get_metrics_response() -> Response:
    """Returns standard Prometheus exposition format."""
    return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
