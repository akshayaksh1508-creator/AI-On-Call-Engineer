"""Payments Service - Handles payment authorization and capture."""

import os
import uuid
from typing import Dict, Any
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from target_app.common.config import settings
from target_app.common.logging import setup_logger
from target_app.common.metrics import add_telemetry_middleware, get_metrics_response

SERVICE_NAME = "payments"
logger = setup_logger(SERVICE_NAME)

app = FastAPI(
    title="NightShift Payments Service",
    description="Processes transaction payments and charges",
    version=settings.VERSION,
)

# Attach telemetry & JSON logging middleware
add_telemetry_middleware(app, SERVICE_NAME, logger)

# In-memory storage of processed payments
payments_db: Dict[str, Dict[str, Any]] = {}


class PaymentRequest(BaseModel):
    order_id: str = Field(..., description="Order identifier")
    amount: float = Field(..., gt=0, description="Payment amount must be positive")
    currency: str = Field(default="USD", description="Currency code")


class PaymentResponse(BaseModel):
    payment_id: str
    order_id: str
    status: str
    amount: float
    currency: str


@app.get("/health")
def health() -> Dict[str, Any]:
    """Healthcheck endpoint (Section 14: curl /health returns 200)."""
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "version": settings.VERSION,
    }


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return get_metrics_response()


@app.post("/process", response_model=PaymentResponse, status_code=200)
def process_payment(req: PaymentRequest, request: Request) -> PaymentResponse:
    """Processes payment for an order and logs trace context."""
    trace_id = getattr(request.state, "trace_id", "unknown")
    logger.info(
        f"Processing payment of {req.amount} {req.currency} for order {req.order_id}",
        extra={"trace_id": trace_id, "extra_fields": {"order_id": req.order_id, "amount": req.amount}},
    )

    # Simulated validation rule: reject amounts exceeding $50,000 as potential fraud
    if req.amount > 50000.0:
        logger.error(
            f"Payment rejected: amount {req.amount} exceeds fraud limit",
            extra={"trace_id": trace_id, "extra_fields": {"order_id": req.order_id}},
        )
        raise HTTPException(status_code=400, detail="Transaction amount exceeds safety limit")

    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    record = {
        "payment_id": payment_id,
        "order_id": req.order_id,
        "status": "APPROVED",
        "amount": req.amount,
        "currency": req.currency,
    }
    payments_db[payment_id] = record

    logger.info(
        f"Payment {payment_id} APPROVED for order {req.order_id}",
        extra={"trace_id": trace_id, "extra_fields": {"payment_id": payment_id}},
    )

    return PaymentResponse(**record)


@app.get("/payments/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: str, request: Request) -> PaymentResponse:
    trace_id = getattr(request.state, "trace_id", "unknown")
    record = payments_db.get(payment_id)
    if not record:
        logger.warning(
            f"Payment {payment_id} not found",
            extra={"trace_id": trace_id},
        )
        raise HTTPException(status_code=404, detail="Payment record not found")
    return PaymentResponse(**record)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.PAYMENTS_PORT)
