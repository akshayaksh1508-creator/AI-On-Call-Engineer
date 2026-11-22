"""API Gateway Service - Front door routing requests to downstream microservices."""

from typing import Dict, Any, List
import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from target_app.common.config import settings
from target_app.common.logging import setup_logger
from target_app.common.metrics import add_telemetry_middleware, get_metrics_response

SERVICE_NAME = "gateway"
logger = setup_logger(SERVICE_NAME)

app = FastAPI(
    title="NightShift API Gateway",
    description="Edge routing, tracing, and rate/error telemetry aggregation",
    version=settings.VERSION,
)

# Attach telemetry & JSON logging middleware
add_telemetry_middleware(app, SERVICE_NAME, logger)


class GatewayOrderRequest(BaseModel):
    customer_id: str = Field(..., description="Customer ID")
    item: str = Field(..., description="Item ordered")
    quantity: int = Field(default=1, gt=0)
    price: float = Field(..., gt=0)


@app.get("/health")
def health() -> Dict[str, Any]:
    """Gateway health check (Section 14: curl /health returns 200)."""
    return {
        "status": "healthy",
        "service": SERVICE_NAME,
        "version": settings.VERSION,
    }


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return get_metrics_response()


@app.post("/api/orders", status_code=201)
async def create_order_endpoint(order_req: GatewayOrderRequest, request: Request) -> Dict[str, Any]:
    """Ingests order request, propagates trace context, forwards to orders service."""
    trace_id = getattr(request.state, "trace_id", "unknown")
    logger.info(
        f"Gateway received order request for customer {order_req.customer_id}",
        extra={"trace_id": trace_id, "extra_fields": {"item": order_req.item, "quantity": order_req.quantity}},
    )

    downstream_url = f"{settings.ORDERS_SERVICE_URL}/orders"
    headers = {"X-Trace-ID": trace_id}

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                downstream_url, json=order_req.model_dump(), headers=headers
            )
            if resp.status_code == 201:
                logger.info(
                    f"Gateway successfully routed order creation (status: 201)",
                    extra={"trace_id": trace_id, "extra_fields": {"downstream_status": resp.status_code}},
                )
                return resp.json()
            else:
                logger.error(
                    f"Downstream orders service responded with status {resp.status_code}: {resp.text}",
                    extra={"trace_id": trace_id, "extra_fields": {"downstream_status": resp.status_code}},
                )
                raise HTTPException(status_code=resp.status_code, detail=resp.text)

    except httpx.RequestError as exc:
        logger.error(
            f"Gateway failed to connect to orders service at {downstream_url}: {exc}",
            extra={"trace_id": trace_id},
        )
        raise HTTPException(status_code=503, detail="Orders service temporarily unavailable")


@app.get("/api/orders")
async def list_orders_endpoint(request: Request) -> List[Dict[str, Any]]:
    trace_id = getattr(request.state, "trace_id", "unknown")
    downstream_url = f"{settings.ORDERS_SERVICE_URL}/orders"
    headers = {"X-Trace-ID": trace_id}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(downstream_url, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except httpx.RequestError as exc:
        logger.error(f"Gateway failed to reach orders service: {exc}", extra={"trace_id": trace_id})
        raise HTTPException(status_code=503, detail="Orders service temporarily unavailable")


@app.get("/api/orders/{order_id}")
async def get_order_endpoint(order_id: str, request: Request) -> Dict[str, Any]:
    trace_id = getattr(request.state, "trace_id", "unknown")
    downstream_url = f"{settings.ORDERS_SERVICE_URL}/orders/{order_id}"
    headers = {"X-Trace-ID": trace_id}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(downstream_url, headers=headers)
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except httpx.RequestError as exc:
        logger.error(f"Gateway failed to reach orders service: {exc}", extra={"trace_id": trace_id})
        raise HTTPException(status_code=503, detail="Orders service temporarily unavailable")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.GATEWAY_PORT)
