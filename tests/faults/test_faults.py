"""Unit and Integration Tests for Fault Injector Framework and Fault 1.

Verifies:
1. Manifest schema validation and catalog discovery.
2. Fault injection (`apply`) causing HTTP 500 error spike on orders service.
3. Fault rollback (`revert`) restoring healthy baseline (<1% errors).
4. Code patch verification (`patch`) confirming defensive check remediation.
5. Change event logging to data/changes.json.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient

from faults.manifest import FaultManifest
from faults.injector import injector, TARGET_APP_DIR, CHANGES_FILE


class TestFaultInjector(unittest.TestCase):
    """Test suite for FaultInjector and fault_001_bad_deploy."""

    def setUp(self):
        # Ensure clean state before each test
        injector.revert("fault_001_bad_deploy", record_change=False)

        # Mock downstream payments service for offline unit test speed
        self.mock_post = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "APPROVED", "payment_id": "pay_mock_123"}
        mock_resp.text = '{"status": "APPROVED", "payment_id": "pay_mock_123"}'
        self.mock_post.return_value = mock_resp

        self.patcher = patch("httpx.AsyncClient.post", self.mock_post)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        # Restore clean state after each test
        injector.revert("fault_001_bad_deploy", record_change=False)

    def test_01_manifest_validation(self):
        """FaultManifest schema parses valid metadata and checks defaults."""
        manifest = FaultManifest(
            fault_id="fault_test_001",
            title="Test Fault",
            category="code",
            target_service="orders",
            culprit_change="dep_test_001",
            root_cause="Test root cause mechanism",
        )
        self.assertEqual(manifest.fault_id, "fault_test_001")
        self.assertEqual(manifest.expected_fix_type, "patch")
        self.assertEqual(manifest.risk_tier, "T2")
        self.assertEqual(manifest.rollback_version, "v1.0.0")

    def test_02_catalog_discovery(self):
        """FaultInjector discovers fault_001_bad_deploy from catalog."""
        faults = injector.list_faults()
        self.assertGreater(len(faults), 0)
        ids = [f.get("fault_id") for f in faults]
        self.assertIn("fault_001_bad_deploy", ids)

        fault_obj = injector.get_fault("fault_001_bad_deploy")
        self.assertEqual(fault_obj.fault_id, "fault_001_bad_deploy")
        self.assertEqual(fault_obj.target_service, "orders")
        self.assertEqual(fault_obj.category, "code")
        self.assertEqual(fault_obj.culprit_change, "dep_20261122_v1.0.1")

    def test_03_apply_fault_001_bad_deploy(self):
        """Applying fault_001_bad_deploy causes POST /orders to return 500."""
        res = injector.apply("fault_001_bad_deploy")
        self.assertEqual(res["status"], "applied")

        status = injector.status()
        self.assertTrue(status.get("active"))
        self.assertEqual(status.get("fault_id"), "fault_001_bad_deploy")

        # Verify version.txt was updated to v1.0.1
        version_txt = (TARGET_APP_DIR / "version.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(version_txt, "v1.0.1")

        # Verify change event was logged in changes.json
        with open(CHANGES_FILE, "r", encoding="utf-8") as f:
            changes = json.load(f)
        self.assertTrue(any(c.get("version") == "v1.0.1" for c in changes))

        # Dynamically import orders app and test failing request
        import importlib
        import target_app.services.orders.app as orders_module
        importlib.reload(orders_module)

        client = TestClient(orders_module.app, raise_server_exceptions=False)

        # Standard checkout request without discount should FAIL with 500
        req_payload = {
            "customer_id": "cust_test_fault",
            "item": "laptop",
            "quantity": 1,
            "price": 999.0,
        }
        resp = client.post("/orders", json=req_payload)
        self.assertEqual(resp.status_code, 500, "Faulty orders service must return 500 on None discount")

        # Checkout request WITH valid discount should SUCCEED with 201 (VIP feature works for VIPs)
        vip_payload = {
            "customer_id": "cust_vip",
            "item": "laptop",
            "quantity": 1,
            "price": 1000.0,
            "discount": {"code": "VIP50"},
        }
        resp_vip = client.post("/orders", json=vip_payload)
        self.assertEqual(resp_vip.status_code, 201)
        self.assertEqual(resp_vip.json()["total"], 500.0)

    def test_04_revert_fault_001_bad_deploy(self):
        """Reverting fault_001_bad_deploy restores orders service to healthy 201 status."""
        # 1. Apply fault
        injector.apply("fault_001_bad_deploy")

        # 2. Revert fault
        res = injector.revert("fault_001_bad_deploy")
        self.assertEqual(res["status"], "reverted")

        status = injector.status()
        self.assertFalse(status.get("active"))

        # Verify version.txt was restored to v1.0.0
        version_txt = (TARGET_APP_DIR / "version.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(version_txt, "v1.0.0")

        # Dynamically reload orders app and test normal request
        import importlib
        import target_app.services.orders.app as orders_module
        importlib.reload(orders_module)

        client = TestClient(orders_module.app, raise_server_exceptions=False)

        # Standard checkout request without discount should SUCCEED with 201
        req_payload = {
            "customer_id": "cust_recovered",
            "item": "keyboard",
            "quantity": 1,
            "price": 89.0,
        }
        resp = client.post("/orders", json=req_payload)
        self.assertEqual(resp.status_code, 201, "Reverted orders service must return 201 on checkout")
        self.assertEqual(resp.json()["status"], "CONFIRMED")

    def test_05_patch_remediation(self):
        """Applying defensive patch resolves the null pointer while keeping VIP feature."""
        # 1. Apply fault first
        injector.apply("fault_001_bad_deploy")

        # 2. Apply patch remediation
        patch_res = injector.patch("fault_001_bad_deploy")
        self.assertEqual(patch_res["status"], "patched")

        # Dynamically reload orders app
        import importlib
        import target_app.services.orders.app as orders_module
        importlib.reload(orders_module)

        client = TestClient(orders_module.app, raise_server_exceptions=False)

        # Standard checkout request without discount NOW SUCCEEDS with 201
        req_payload = {
            "customer_id": "cust_patched",
            "item": "mouse",
            "quantity": 2,
            "price": 25.0,
        }
        resp = client.post("/orders", json=req_payload)
        self.assertEqual(resp.status_code, 201, "Patched orders service must succeed without discount")
        self.assertEqual(resp.json()["total"], 50.0)

        # VIP checkout still receives discount
        vip_payload = {
            "customer_id": "cust_vip_patched",
            "item": "monitor",
            "quantity": 1,
            "price": 400.0,
            "discount": {"code": "VIP50"},
        }
        resp_vip = client.post("/orders", json=vip_payload)
        self.assertEqual(resp_vip.status_code, 201)
        self.assertEqual(resp_vip.json()["total"], 200.0)

    def test_06_idempotent_revert(self):
        """Reverting when no fault is active is safe and preserves v1.0.0."""
        res = injector.revert("fault_001_bad_deploy")
        self.assertEqual(res["status"], "reverted")
        version_txt = (TARGET_APP_DIR / "version.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(version_txt, "v1.0.0")


if __name__ == "__main__":
    unittest.main()
