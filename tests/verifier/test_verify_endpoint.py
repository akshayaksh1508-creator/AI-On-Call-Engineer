"""Unit tests for Unified /verify endpoint (Day 5 Task A4)."""

import unittest
from pathlib import Path
from starlette.testclient import TestClient

from contracts import get_schema
from contracts.models import VerificationResult
from platform_api.app import create_platform_api_app


class TestVerifyEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[2]
        cls.app = create_platform_api_app(
            mode="fixture",
            fixture_bundle="fault_001_bad_deploy",
            repo_root=cls.repo_root,
            sandbox_use_container=False,
        )
        cls.client = TestClient(cls.app)

        # A valid defensive patch for fault_001_bad_deploy
        target_file = "target-app/services/orders/app.py"
        cls.good_patch = (
            f"diff --git a/{target_file} b/{target_file}\n"
            f"--- a/{target_file}\n+++ b/{target_file}\n"
            "@@ -87,7 +87,7 @@\n"
            "         raw_body = {}\n"
            "     discount = raw_body.get(\"discount\")\n"
            "     # BUG: Developer assumes discount is always a dict and accesses [\"code\"] directly\n"
            "-    discount_code = discount[\"code\"]  # Raises TypeError: 'NoneType' object is not subscriptable!\n"
            "+    discount_code = discount.get(\"code\") if isinstance(discount, dict) else None  # Raises TypeError: 'NoneType' object is not subscriptable!\n"
            "     if discount_code == \"VIP50\":\n"
            "         total = round(total * 0.50, 2)\n \n"
        )
        cls.bad_patch = (
            f"diff --git a/{target_file} b/{target_file}\n"
            f"--- a/{target_file}\n+++ b/{target_file}\n"
            "@@ -87,7 +87,7 @@\n"
            "         raw_body = {}\n"
            "     discount = raw_body.get(\"discount\")\n"
            "     # BUG: Developer assumes discount is always a dict and accesses [\"code\"] directly\n"
            "-    discount_code = discount[\"code\"]  # Raises TypeError: 'NoneType' object is not subscriptable!\n"
            "+    raise RuntimeError('deliberately broken fix')\n"
            "     if discount_code == \"VIP50\":\n"
            "         total = round(total * 0.50, 2)\n \n"
        )

    def test_verify_returns_full_verification_result_contract(self):
        """Task A4 criterion: JSON validates against the contract schema."""
        resp = self.client.post(
            "/verify",
            json={
                "incident_id": "inc-test-a4",
                "fault_id": "fault_001_bad_deploy",
                "patch": self.good_patch,
                "simulated_canary_healthy": True,
                "post_promotion_error_rate": 0.002,
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()

        # 1. Validates against VerificationResult Pydantic contract
        result = VerificationResult.model_validate(data)
        self.assertEqual(result.verdict, "PASS")
        self.assertTrue(result.tests_passed)
        self.assertTrue(result.repro_fixed)
        self.assertTrue(result.canary_healthy)
        self.assertIsNotNone(result.recovered_at)

        # 2. Schema required fields check
        schema = get_schema("VerificationResult")
        for req_field in schema.get("required", []):
            self.assertIn(req_field, data, f"Required field '{req_field}' missing from /verify response")

    def test_numbers_equal_direct_prometheus_query(self):
        """Task A4 criterion: The numbers equal a direct Prometheus query."""
        # 1. Query the direct Prometheus metrics query endpoint
        prom_resp = self.client.get("/metrics/query", params={"metric_name": "http_requests_total"})
        self.assertEqual(prom_resp.status_code, 200)
        prom_data = prom_resp.json()

        # Extract direct error rate from Prometheus time series
        total_requests = 0.0
        error_requests = 0.0
        for series in prom_data.get("data", {}).get("result", []):
            metric = series.get("metric", {})
            status = str(metric.get("status", "200"))
            values = series.get("values", []) or [series.get("value", [0, 0])]
            if values:
                val = float(values[-1][1]) if len(values[-1]) > 1 else 0.0
                total_requests += val
                if status.startswith("5"):
                    error_requests += val

        expected_direct_error_rate = (
            round(error_requests / total_requests, 4) if total_requests > 0 else 0.15
        )

        # 2. Query /verify endpoint
        verify_resp = self.client.post(
            "/verify",
            json={
                "incident_id": "inc-prom-parity",
                "fault_id": "fault_001_bad_deploy",
                "patch": self.good_patch,
                "simulated_canary_healthy": True,
                "post_promotion_error_rate": 0.001,
            },
        )
        self.assertEqual(verify_resp.status_code, 200)
        verify_data = verify_resp.json()

        # 3. Assert metric_before in /verify equals direct Prometheus query calculation
        self.assertEqual(verify_data["metric_before"], expected_direct_error_rate)
        # End-of-day gate: outputs before and after error-rate numbers
        self.assertIsInstance(verify_data["metric_before"], float)
        self.assertIsInstance(verify_data["metric_after"], float)
        self.assertGreater(verify_data["metric_before"], verify_data["metric_after"])

    def test_bad_patch_fails_sandbox_and_returns_fail_verdict(self):
        """A broken patch fails the sandbox stage and returns verdict=FAIL."""
        resp = self.client.post(
            "/verify",
            json={
                "incident_id": "inc-bad-patch",
                "fault_id": "fault_001_bad_deploy",
                "patch": self.bad_patch,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        result = VerificationResult.model_validate(data)
        self.assertEqual(result.verdict, "FAIL")
        self.assertFalse(result.tests_passed)
        self.assertFalse(result.canary_healthy)
        self.assertIsNone(result.recovered_at)

    def test_unhealthy_canary_returns_fail_verdict(self):
        """If canary stage detects degradation, verdict is FAIL."""
        resp = self.client.post(
            "/verify",
            json={
                "incident_id": "inc-bad-canary",
                "fault_id": "fault_001_bad_deploy",
                "patch": self.good_patch,
                "simulated_canary_healthy": False,
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        result = VerificationResult.model_validate(data)
        self.assertEqual(result.verdict, "FAIL")
        self.assertTrue(result.tests_passed)
        self.assertTrue(result.repro_fixed)
        self.assertFalse(result.canary_healthy)

    def test_post_promotion_regression_triggers_rollback_verdict(self):
        """If metrics degrade after promotion, auto-rollback triggers and verdict=ROLLBACK."""
        resp = self.client.post(
            "/verify",
            json={
                "incident_id": "inc-rollback",
                "fault_id": "fault_001_bad_deploy",
                "patch": self.good_patch,
                "simulated_canary_healthy": True,
                "post_promotion_error_rate": 0.95,  # 95% error rate (worse than baseline 90%)
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        result = VerificationResult.model_validate(data)
        self.assertEqual(result.verdict, "ROLLBACK")
        self.assertTrue(result.canary_healthy)
        self.assertGreater(result.metric_after, result.metric_before)


if __name__ == "__main__":
    unittest.main()
