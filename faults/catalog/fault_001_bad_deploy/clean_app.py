"""Orders Service - Manages customer orders and coordinates with Payments."""

import os
import sys
from pathlib import Path

# Ensure repository root is in sys.path
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import uuid
from typing import Dict, Any, List
import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from target_app.common.config import settings
from target_app.common.logging import setup_logger
from target_app.common.metrics import add_telemetry_middleware, get_metrics_response
from target_app.services.orders.db import db

SERVICE_NAME = "orders"
logger = setup_logger(SERVICE_NAME)

app = FastAPI(
    title="NightShift Orders Service",
    description="Manages order creation, lifecycle, and payments coordination",
    version=settings.VERSION,
)

# Attach telemetry & JSON logging middleware
add_telemetry_middleware(app, SERVICE_NAME, logger)


class CreateOrderRequest(BaseModel):
    customer_id: str = Field(..., description="Customer identifier")
    item: str = Field(..., description="Item or product name")
    quantity: int = Field(default=1, gt=0, description="Quantity to order")
    price: float = Field(..., gt=0, description="Unit price")


class OrderResponse(BaseModel):
    order_id: str
    customer_id: str
    item: str
    quantity: int
    price: float
    total: float
    status: str
    payment_id: str = ""


@app.get("/health")
def health() -> Dict[str, Any]:
    """Healthcheck endpoint (Section 14: curl /health returns 200)."""
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "version": settings.VERSION,
        "database": "postgres" if db.use_postgres else "sqlite",
    }


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return get_metrics_response()


@app.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(req: CreateOrderRequest, request: Request) -> OrderResponse:
    trace_id = getattr(request.state, "trace_id", "unknown")
    order_id = f"ord_{uuid.uuid4().hex[:12]}"
    total = round(req.quantity * req.price, 2)

    logger.info(
        f"Creating order {order_id} for customer {req.customer_id} (total: ${total})",
        extra={"trace_id": trace_id, "extra_fields": {"order_id": order_id, "total": total}},
    )

    # 1. Save initial order as PENDING
    order_record = {
        "order_id": order_id,
        "customer_id": req.customer_id,
        "item": req.item,
        "quantity": req.quantity,
        "price": req.price,
        "total": total,
        "status": "PENDING",
    }
    db.save_order(order_record)

    # 2. Downstream call to Payments service with Trace ID propagation
    payment_url = f"{settings.PAYMENTS_SERVICE_URL}/process"
    payment_payload = {
        "order_id": order_id,
        "amount": total,
        "currency": "USD",
    }
    headers = {"X-Trace-ID": trace_id}

    logger.info(
        f"Forwarding payment request for order {order_id} to payments service at {payment_url}",
        extra={"trace_id": trace_id, "extra_fields": {"target": "payments"}},
    )

    payment_id = ""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(payment_url, json=payment_payload, headers=headers)
            if resp.status_code == 200:
                payment_data = resp.json()
                payment_id = payment_data.get("payment_id", "")
                order_record["status"] = "CONFIRMED"
                logger.info(
                    f"Order {order_id} confirmed; payment {payment_id} approved",
                    extra={"trace_id": trace_id, "extra_fields": {"payment_id": payment_id, "order_status": "CONFIRMED"}},
                )
            else:
                order_record["status"] = "PAYMENT_FAILED"
                logger.error(
                    f"Payment service rejected order {order_id} with status {resp.status_code}: {resp.text}",
                    extra={"trace_id": trace_id, "extra_fields": {"order_id": order_id}},
                )
                db.save_order(order_record)
                raise HTTPException(status_code=400, detail=f"Payment processing failed: {resp.text}")

    except httpx.RequestError as exc:
        order_record["status"] = "PAYMENT_UNREACHABLE"
        db.save_order(order_record)
        logger.error(
            f"Failed to reach payments service for order {order_id}: {exc}",
            extra={"trace_id": trace_id},
        )
        raise HTTPException(status_code=503, detail="Payments service unreachable")

    db.save_order(order_record)
    return OrderResponse(
        order_id=order_id,
        customer_id=req.customer_id,
        item=req.item,
        quantity=req.quantity,
        price=req.price,
        total=total,
        status=order_record["status"],
        payment_id=payment_id,
    )


@app.get("/orders", response_model=List[OrderResponse])
def list_orders(request: Request) -> List[OrderResponse]:
    orders = db.list_orders()
    return [OrderResponse(**o) for o in orders]


@app.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: str, request: Request) -> OrderResponse:
    trace_id = getattr(request.state, "trace_id", "unknown")
    order = db.get_order(order_id)
    if not order:
        logger.warning(f"Order {order_id} not found", extra={"trace_id": trace_id})
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderResponse(**order)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.ORDERS_PORT)
