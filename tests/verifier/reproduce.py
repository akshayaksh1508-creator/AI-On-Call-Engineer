"""Replay the failing input for one of the five Day 4 code fault fixtures."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
TARGET_APP = REPO / "target-app"
sys.path.insert(0, str(TARGET_APP))
sys.path.insert(0, str(REPO))


def reproduce(fault_id: str) -> None:
    if fault_id == "fault_001_bad_deploy":
        from fastapi import Request
        from services.orders import app as orders

        class Response:
            status_code = 200
            text = "{}"

            @staticmethod
            def json():
                return {"payment_id": "pay-repro"}

        class AsyncClient:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def post(self, *_args, **_kwargs):
                return Response()

        class FakeRequest:
            state = SimpleNamespace(trace_id="day4-reproduction")

            @staticmethod
            async def json():
                return {"customer_id": "repro", "item": "item", "quantity": 1, "price": 5}

        original_client = orders.httpx.AsyncClient
        original_save = orders.db.save_order
        orders.httpx.AsyncClient = AsyncClient
        orders.db.save_order = lambda _order: None
        try:
            request = FakeRequest()
            coroutine = orders.create_order(
                orders.CreateOrderRequest(customer_id="repro", item="item", quantity=1, price=5),
                request,
            )
            try:
                coroutine.send(None)
            except StopIteration as completed:
                response = completed.value
            else:
                raise RuntimeError("reproduction unexpectedly performed asynchronous I/O")
            assert response.status == "CONFIRMED"
        except TypeError as exc:
            raise AssertionError("missing optional discount crashed order creation") from exc
        finally:
            orders.httpx.AsyncClient = original_client
            orders.db.save_order = original_save
    elif fault_id == "fault_002_off_by_one":
        from services.orders import app as orders

        if not hasattr(orders, "paginate_records"):
            raise unittest.SkipTest("The clean baseline has no pagination fault implementation")

        records = [{"id": 1}, {"id": 2}]
        assert orders.paginate_records(records, page=1, limit=1) == [records[0]]
    elif fault_id == "fault_003_wrong_status_code":
        from fastapi import HTTPException
        from services.payments.app import app
        from services.payments.app import PaymentRequest, process_payment

        request = SimpleNamespace(state=SimpleNamespace(trace_id="day4-reproduction"))
        try:
            process_payment(PaymentRequest(order_id="repro", amount=10, currency="DECLINE"), request)
        except HTTPException as exc:
            assert exc.status_code == 402, f"declined payment returned HTTP {exc.status_code}"
        else:
            raise AssertionError("declined payment returned an HTTP 200 response")
    elif fault_id == "fault_004_bad_parsing":
        from services.gateway.app import parse_request_timestamp

        value = parse_request_timestamp("2026-11-23T12:30:00Z")
        assert value.isoformat().startswith("2026-11-23T12:30:00")
    elif fault_id == "fault_005_unhandled_exception":
        from services.orders import app as orders

        if not hasattr(orders, "calculate_unit_discount"):
            raise unittest.SkipTest("The clean baseline has no promotional discount implementation")

        assert orders.calculate_unit_discount(15.0, 0) == 0.0
    else:
        raise ValueError(f"Unknown Day 4 reproduction: {fault_id}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: reproduce.py fault_001_bad_deploy")
    reproduce(sys.argv[1])
