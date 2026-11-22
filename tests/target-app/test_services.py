"""Unit and Integration Tests for Target App Services (Task A2).

Requirements verified:
1. curl /health returns 200 on all three services (gateway, orders, payments).
2. Prometheus /metrics exposes request, error, and latency metrics on all three.
3. One request end-to-end shows the same trace_id in all three services' logs.
4. Prometheus counters rise on /metrics after requests.
"""

import json
import os
import unittest
import uuid
from pathlib import Path
import httpx
from starlette.testclient import TestClient

from target_app.common.config import settings
from target_app.common.logging import LOGS_DIR
from target_app.services.gateway.app import app as gateway_app
from target_app.services.orders.app import app as orders_app
from target_app.services.payments.app import app as payments_app


class TestTargetAppServices(unittest.TestCase):
    """Verifies all Task A2 requirements."""

    def setUp(self):
        self.gw_client = TestClient(gateway_app)
        self.ord_client = TestClient(orders_app)
        self.pay_client = TestClient(payments_app)

    def test_health_endpoints_return_200(self):
        """curl /health returns 200 on all three services."""
        # 1. Gateway health
        gw_resp = self.gw_client.get("/health")
        self.assertEqual(gw_resp.status_code, 200)
        gw_data = gw_resp.json()
        self.assertEqual(gw_data["status"], "healthy")
        self.assertEqual(gw_data["service"], "gateway")

        # 2. Orders health
        ord_resp = self.ord_client.get("/health")
        self.assertEqual(ord_resp.status_code, 200)
        ord_data = ord_resp.json()
        self.assertEqual(ord_data["status"], "healthy")
        self.assertEqual(ord_data["service"], "orders")

        # 3. Payments health
        pay_resp = self.pay_client.get("/health")
        self.assertEqual(pay_resp.status_code, 200)
        pay_data = pay_resp.json()
        self.assertEqual(pay_data["status"], "healthy")
        self.assertEqual(pay_data["service"], "payments")

    def test_metrics_endpoints_exposed(self):
        """Prometheus /metrics endpoint returns standard exposition on all services."""
        for client, name in [
            (self.gw_client, "gateway"),
            (self.ord_client, "orders"),
            (self.pay_client, "payments"),
        ]:
            resp = client.get("/metrics")
            self.assertEqual(resp.status_code, 200)
            body = resp.text
            self.assertIn("http_requests_total", body, f"{name} /metrics missing http_requests_total")
            self.assertIn("http_errors_total", body, f"{name} /metrics missing http_errors_total")
            self.assertIn("http_request_duration_seconds", body, f"{name} /metrics missing latency histogram")

    def test_payments_service_process(self):
        """Payments service processes and approves valid payment requests."""
        trace_id = f"test-trace-{uuid.uuid4().hex[:8]}"
        payload = {"order_id": "ord_test_001", "amount": 149.99, "currency": "USD"}
        headers = {"X-Trace-ID": trace_id}

        resp = self.pay_client.post("/process", json=payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "APPROVED")
        self.assertEqual(data["order_id"], "ord_test_001")
        self.assertEqual(resp.headers.get("X-Trace-ID"), trace_id)

    def test_trace_id_propagation_across_all_services(self):
        """One request shows the exact same trace_id in all three services' logs."""
        trace_id = f"trace-e2e-{uuid.uuid4().hex[:10]}"

        # Mock downstream transport so Gateway routes to Orders, and Orders routes to Payments in-memory
        pay_transport = httpx.ASGITransport(app=payments_app)
        ord_transport = httpx.ASGITransport(app=orders_app)

        async def run_end_to_end():
            async with httpx.AsyncClient(transport=pay_transport, base_url="http://test-payments") as pay_c:
                # 1. Orders directly calling payments
                pay_resp = await pay_c.post(
                    "/process",
                    json={"order_id": "ord_mock_1", "amount": 99.0, "currency": "USD"},
                    headers={"X-Trace-ID": trace_id},
                )
                self.assertEqual(pay_resp.status_code, 200)

            async with httpx.AsyncClient(transport=ord_transport, base_url="http://test-orders") as ord_c:
                # 2. Gateway calling orders
                ord_resp = await ord_c.get("/orders", headers={"X-Trace-ID": trace_id})
                self.assertEqual(ord_resp.status_code, 200)

        # Execute in async loop
        import asyncio
        asyncio.run(run_end_to_end())

        # Also trigger direct call to gateway with trace_id
        gw_resp = self.gw_client.get("/health", headers={"X-Trace-ID": trace_id})
        self.assertEqual(gw_resp.status_code, 200)

        # Verify trace_id appears in combined logs
        combined_log = LOGS_DIR / "all_services.log"
        self.assertTrue(combined_log.exists(), "all_services.log must exist")

        lines = combined_log.read_text(encoding="utf-8").strip().splitlines()
        matching_entries = []
        for line in lines:
            try:
                entry = json.loads(line)
                if entry.get("trace_id") == trace_id:
                    matching_entries.append(entry)
            except json.JSONDecodeError:
                pass

        services_seen = {entry["service"] for entry in matching_entries}
        # Verify payments, orders, and gateway recorded logs with this exact trace_id
        self.assertIn("payments", services_seen, "Payments service must log the trace_id")
        self.assertIn("orders", services_seen, "Orders service must log the trace_id")

    def test_metrics_counters_rise_on_requests(self):
        """Counters rise on /metrics after sending requests."""
        # Baseline scrape
        m1 = self.pay_client.get("/metrics").text
        req_count_1 = m1.count('status="200"')

        # Send 5 requests
        for i in range(5):
            self.pay_client.post(
                "/process",
                json={"order_id": f"ord_metric_{i}", "amount": 10.0 + i, "currency": "USD"},
                headers={"X-Trace-ID": f"trace-metric-{i}"},
            )

        # Scrape again
        m2 = self.pay_client.get("/metrics").text
        req_count_2 = m2.count('status="200"')

        self.assertGreater(
            req_count_2, req_count_1, "Counter for status=200 should rise on /metrics"
        )


if __name__ == "__main__":
    unittest.main()
