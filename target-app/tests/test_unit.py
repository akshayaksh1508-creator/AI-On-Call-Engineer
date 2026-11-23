"""12 Comprehensive Unit Tests for NightShift Target App (Task A3).

Requirement:
"the app's own git repo (/target-app) with 10 or more unit tests"
"How to test: unit tests pass"
"""

import json
import logging
import os
import sys
import unittest
import uuid
from pathlib import Path

# Ensure paths
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

target_app_dir = Path(__file__).resolve().parent.parent
if str(target_app_dir) not in sys.path:
    sys.path.insert(0, str(target_app_dir))

from starlette.testclient import TestClient

from target_app.common.config import settings
from target_app.common.logging import JsonFormatter
from target_app.common.metrics import (
    REQUESTS_TOTAL,
    ERRORS_TOTAL,
    get_metrics_response,
)
from target_app.services.gateway.app import app as gateway_app
from target_app.services.orders.app import app as orders_app
from target_app.services.orders.db import OrderDB
from target_app.services.payments.app import app as payments_app, payments_db


class TestTargetAppUnit(unittest.TestCase):
    """12 Comprehensive Unit Tests for Target App Components."""

    def setUp(self):
        self.gw_client = TestClient(gateway_app)
        self.ord_client = TestClient(orders_app)
        self.pay_client = TestClient(payments_app)
        self.test_db = OrderDB()

    # Test 1: Gateway Health
    def test_01_gateway_health(self):
        resp = self.gw_client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "gateway")
        self.assertTrue(len(data["version"]) > 0)

    # Test 2: Orders Health
    def test_02_orders_health(self):
        resp = self.ord_client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "orders")
        self.assertIn("database", data)

    # Test 3: Payments Health
    def test_03_payments_health(self):
        resp = self.pay_client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "payments")

    # Test 4: Payments Process Approved
    def test_04_payments_process_approved(self):
        trace_id = f"trace-test-{uuid.uuid4().hex[:6]}"
        payload = {"order_id": "ord_unit_101", "amount": 250.00, "currency": "USD"}
        resp = self.pay_client.post("/process", json=payload, headers={"X-Trace-ID": trace_id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "APPROVED")
        self.assertEqual(data["order_id"], "ord_unit_101")
        self.assertEqual(data["amount"], 250.00)
        self.assertTrue(data["payment_id"].startswith("pay_"))

    # Test 5: Payments Fraud Limit Rejection (> $50,000)
    def test_05_payments_fraud_limit_rejection(self):
        payload = {"order_id": "ord_unit_fraud", "amount": 999999.00, "currency": "USD"}
        resp = self.pay_client.post("/process", json=payload)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("exceeds safety limit", resp.json()["detail"])

    # Test 6: Payments Retrieval by ID and 404 on Missing
    def test_06_payments_lookup(self):
        # Insert known payment directly into active payments database
        pay_id = f"pay_unit_{uuid.uuid4().hex[:6]}"
        import target_app.services.payments.app as current_pay_app
        current_pay_app.payments_db[pay_id] = {
            "payment_id": pay_id,
            "order_id": "ord_unit_lookup",
            "status": "APPROVED",
            "amount": 75.0,
            "currency": "USD",
        }
        resp = self.pay_client.get(f"/payments/{pay_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["payment_id"], pay_id)

        # 404 on non-existent payment
        resp404 = self.pay_client.get("/payments/non_existent_pay_id")
        self.assertEqual(resp404.status_code, 404)

    # Test 7: Orders DB Persistence Save & Get
    def test_07_orders_db_save_and_get(self):
        order_id = f"ord_db_{uuid.uuid4().hex[:8]}"
        order = {
            "order_id": order_id,
            "customer_id": "cust_test_db",
            "item": "Test SSD Drive",
            "quantity": 2,
            "price": 89.50,
            "total": 179.00,
            "status": "CONFIRMED",
        }
        self.test_db.save_order(order)
        fetched = self.test_db.get_order(order_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["order_id"], order_id)
        self.assertEqual(fetched["customer_id"], "cust_test_db")
        self.assertEqual(fetched["item"], "Test SSD Drive")
        self.assertEqual(fetched["total"], 179.00)

    # Test 8: Orders DB List with Pagination
    def test_08_orders_db_list(self):
        orders = self.test_db.list_orders(limit=5)
        self.assertIsInstance(orders, list)

    # Test 9: Orders Request Schema Validation
    def test_09_orders_api_validation(self):
        # Invalid: missing item
        resp = self.ord_client.post("/orders", json={"customer_id": "cust_1", "price": 10.0})
        self.assertEqual(resp.status_code, 422)

        # Invalid: quantity <= 0
        resp_qty = self.ord_client.post(
            "/orders", json={"customer_id": "cust_1", "item": "pen", "quantity": 0, "price": 1.0}
        )
        self.assertEqual(resp_qty.status_code, 422)

    # Test 10: Gateway Request Schema Validation
    def test_10_gateway_api_validation(self):
        # Missing required fields
        resp = self.gw_client.post("/api/orders", json={})
        self.assertEqual(resp.status_code, 422)

    # Test 11: Telemetry Structured JSON Log Formatter
    def test_11_telemetry_json_formatting(self):
        formatter = JsonFormatter(service_name="test_service")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg="User %s logged in",
            args=("alice",),
            exc_info=None,
        )
        record.trace_id = "trace-unit-json-001"
        record.extra_fields = {"action": "login", "user_id": 42}

        formatted = formatter.format(record)
        parsed = json.loads(formatted)

        self.assertEqual(parsed["service"], "test_service")
        self.assertEqual(parsed["trace_id"], "trace-unit-json-001")
        self.assertEqual(parsed["level"], "INFO")
        self.assertEqual(parsed["message"], "User alice logged in")
        self.assertEqual(parsed["action"], "login")
        self.assertIn("timestamp", parsed)

    # Test 12: Prometheus Metrics Registry
    def test_12_prometheus_metrics_registry(self):
        REQUESTS_TOTAL.labels(
            service="unit_test", endpoint="/test", method="GET", status="200"
        ).inc()
        ERRORS_TOTAL.labels(
            service="unit_test", endpoint="/test", status_code="500"
        ).inc()

        resp = get_metrics_response()
        body = resp.body.decode("utf-8")
        self.assertIn('http_requests_total{endpoint="/test",method="GET",service="unit_test",status="200"}', body)
        self.assertIn('http_errors_total{endpoint="/test",service="unit_test",status_code="500"}', body)


if __name__ == "__main__":
    unittest.main()
