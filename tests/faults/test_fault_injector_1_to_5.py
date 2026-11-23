"""Unit and Integration Tests for Fault Injector Expansion: Faults 1 to 5.

Verifies:
1. Ground-truth YAML schema compliance for Faults 1-5.
2. Full catalog discovery and FaultManifest model parsing.
3. Apply, revert, and patch lifecycles for each fault (001 to 005).
4. Core Success Criteria: apply() then revert() 3 times -> error rate < 1% every time.
5. Idempotent rollback and active fault state tracking.
"""

import importlib
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient

from faults.manifest import FaultManifest
from faults.injector import injector, TARGET_APP_DIR, CHANGES_FILE


class TestFaultInjector1To5(unittest.TestCase):
    """Test suite for expanded Fault Injector Framework covering Faults 1 to 5."""

    @classmethod
    def setUpClass(cls):
        # Guarantee starting from clean baseline
        injector.revert(record_change=False)

    @classmethod
    def tearDownClass(cls):
        # Guarantee ending in clean baseline
        injector.revert(record_change=False)

    def setUp(self):
        # Mock downstream HTTP calls for fast offline execution
        async def mock_post(url, **kwargs):
            mock_resp = MagicMock()
            url_str = str(url)
            if "/process" in url_str:
                mock_resp.status_code = 200
                mock_resp.json.return_value = {"status": "APPROVED", "payment_id": "pay_mock_ok"}
                mock_resp.text = '{"status": "APPROVED", "payment_id": "pay_mock_ok"}'
            elif "/orders" in url_str:
                mock_resp.status_code = 201
                mock_resp.json.return_value = {
                    "order_id": "ord_mock_123",
                    "customer_id": "cust_mock",
                    "item": "laptop",
                    "quantity": 1,
                    "price": 999.0,
                    "total": 999.0,
                    "status": "CONFIRMED",
                    "payment_id": "pay_mock_ok",
                }
                mock_resp.text = '{"order_id": "ord_mock_123", "status": "CONFIRMED"}'
            else:
                mock_resp.status_code = 200
                mock_resp.json.return_value = {}
                mock_resp.text = "{}"
            return mock_resp

        self.http_patcher = patch("httpx.AsyncClient.post", side_effect=mock_post)
        self.http_patcher.start()

    def tearDown(self):
        self.http_patcher.stop()
        # Always revert any active fault after each test
        injector.revert(record_change=False)

    def test_01_all_5_ground_truth_and_manifests_valid(self):
        """Faults 1 through 5 have valid manifests and ground-truth YAML specifications."""
        fault_ids = [
            "fault_001_bad_deploy",
            "fault_002_off_by_one",
            "fault_003_wrong_status_code",
            "fault_004_bad_parsing",
            "fault_005_unhandled_exception",
        ]
        for fid in fault_ids:
            # 1. Manifest parsing
            manifest = injector.get_fault(fid)
            self.assertEqual(manifest.fault_id, fid)
            self.assertEqual(manifest.category, "code")
            self.assertIn(manifest.target_service, ["orders", "payments", "gateway"])
            self.assertTrue(manifest.culprit_change)
            self.assertTrue(manifest.root_cause)

            # 2. Ground-truth YAML parsing
            gt = injector.get_ground_truth(fid)
            self.assertEqual(gt.get("id"), fid)
            self.assertEqual(gt.get("category"), "code")
            self.assertEqual(gt.get("target_service"), manifest.target_service)
            self.assertTrue(gt.get("target_file"))
            self.assertTrue(gt.get("expected_fix"))
            self.assertTrue(gt.get("diff"))

    def test_02_catalog_discovery_all_5(self):
        """FaultInjector discovers and indexes all 5 faults from catalog."""
        catalog = injector.list_faults()
        self.assertGreaterEqual(len(catalog), 5)
        discovered_ids = [f.get("fault_id") for f in catalog]
        for expected in [
            "fault_001_bad_deploy",
            "fault_002_off_by_one",
            "fault_003_wrong_status_code",
            "fault_004_bad_parsing",
            "fault_005_unhandled_exception",
        ]:
            self.assertIn(expected, discovered_ids)

    def test_03_fault_001_lifecycle(self):
        """Fault 1 (VIP discount null pointer) apply, symptom, revert, and patch."""
        # 1. Apply
        res = injector.apply("fault_001_bad_deploy")
        self.assertEqual(res["status"], "applied")
        self.assertTrue(injector.status()["active"])

        import target_app.services.orders.app as orders_mod
        importlib.reload(orders_mod)
        client = TestClient(orders_mod.app, raise_server_exceptions=False)

        # Standard checkout throws 500
        resp_500 = client.post("/orders", json={"customer_id": "c1", "item": "pen", "quantity": 1, "price": 5.0})
        self.assertEqual(resp_500.status_code, 500)

        # VIP checkout succeeds with 201
        resp_vip = client.post("/orders", json={"customer_id": "c1", "item": "pen", "quantity": 1, "price": 10.0, "discount": {"code": "VIP50"}})
        self.assertEqual(resp_vip.status_code, 201)

        # 2. Revert
        injector.revert("fault_001_bad_deploy")
        importlib.reload(orders_mod)
        client_clean = TestClient(orders_mod.app, raise_server_exceptions=False)
        resp_ok = client_clean.post("/orders", json={"customer_id": "c1", "item": "pen", "quantity": 1, "price": 5.0})
        self.assertEqual(resp_ok.status_code, 201)

        # 3. Patch
        injector.patch("fault_001_bad_deploy")
        importlib.reload(orders_mod)
        client_patch = TestClient(orders_mod.app, raise_server_exceptions=False)
        resp_patched = client_patch.post("/orders", json={"customer_id": "c1", "item": "pen", "quantity": 1, "price": 5.0})
        self.assertEqual(resp_patched.status_code, 201)

        injector.revert("fault_001_bad_deploy")

    def test_04_fault_002_lifecycle(self):
        """Fault 2 (Off-by-one pagination) apply, symptom, revert, and patch."""
        # 1. Apply
        injector.apply("fault_002_off_by_one")
        import target_app.services.orders.app as orders_mod
        importlib.reload(orders_mod)
        client = TestClient(orders_mod.app, raise_server_exceptions=False)

        # Populate order
        client.post("/orders", json={"customer_id": "c1", "item": "lamp", "quantity": 1, "price": 20.0})

        # list_orders throws 500 on boundary element index out of range
        resp_err = client.get("/orders")
        self.assertEqual(resp_err.status_code, 500)

        # 2. Revert
        injector.revert("fault_002_off_by_one")
        importlib.reload(orders_mod)
        client_clean = TestClient(orders_mod.app, raise_server_exceptions=False)
        resp_clean = client_clean.get("/orders")
        self.assertEqual(resp_clean.status_code, 200)

        # 3. Patch
        injector.patch("fault_002_off_by_one")
        importlib.reload(orders_mod)
        client_patch = TestClient(orders_mod.app, raise_server_exceptions=False)
        resp_patched = client_patch.get("/orders")
        self.assertEqual(resp_patched.status_code, 200)

        injector.revert("fault_002_off_by_one")

    def test_05_fault_003_lifecycle(self):
        """Fault 3 (Payments 200 with DECLINED body) apply, symptom, revert, and patch."""
        # 1. Apply
        injector.apply("fault_003_wrong_status_code")
        import target_app.services.payments.app as pay_mod
        importlib.reload(pay_mod)
        client = TestClient(pay_mod.app, raise_server_exceptions=False)

        # Decline condition returns 200 with DECLINED status
        resp = client.post("/process", json={"order_id": "ord_decl", "amount": 100.0, "currency": "DECLINE"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "DECLINED")

        # 2. Revert
        injector.revert("fault_003_wrong_status_code")
        importlib.reload(pay_mod)
        client_clean = TestClient(pay_mod.app, raise_server_exceptions=False)
        resp_clean = client_clean.post("/process", json={"order_id": "ord_decl", "amount": 100.0, "currency": "DECLINE"})
        self.assertEqual(resp_clean.status_code, 402)

        # 3. Patch
        injector.patch("fault_003_wrong_status_code")
        importlib.reload(pay_mod)
        client_patch = TestClient(pay_mod.app, raise_server_exceptions=False)
        resp_patch = client_patch.post("/process", json={"order_id": "ord_decl", "amount": 100.0, "currency": "DECLINE"})
        self.assertEqual(resp_patch.status_code, 402)

        injector.revert("fault_003_wrong_status_code")

    def test_06_fault_004_lifecycle(self):
        """Fault 4 (Gateway Zulu timestamp crash) apply, symptom, revert, and patch."""
        # 1. Apply
        injector.apply("fault_004_bad_parsing")
        import target_app.services.gateway.app as gw_mod
        importlib.reload(gw_mod)
        client = TestClient(gw_mod.app, raise_server_exceptions=False)

        # Passing trailing 'Z' causes rigid strptime to raise ValueError -> 500
        resp_err = client.post(
            "/api/orders",
            json={"customer_id": "c1", "item": "book", "quantity": 1, "price": 15.0},
            headers={"X-Request-Timestamp": "2026-11-23T12:00:00Z"},
        )
        self.assertEqual(resp_err.status_code, 500)

        # 2. Revert
        injector.revert("fault_004_bad_parsing")
        importlib.reload(gw_mod)
        client_clean = TestClient(gw_mod.app, raise_server_exceptions=False)
        resp_clean = client_clean.post(
            "/api/orders",
            json={"customer_id": "c1", "item": "book", "quantity": 1, "price": 15.0},
            headers={"X-Request-Timestamp": "2026-11-23T12:00:00Z"},
        )
        self.assertEqual(resp_clean.status_code, 201)

        # 3. Patch
        injector.patch("fault_004_bad_parsing")
        importlib.reload(gw_mod)
        client_patch = TestClient(gw_mod.app, raise_server_exceptions=False)
        resp_patch = client_patch.post(
            "/api/orders",
            json={"customer_id": "c1", "item": "book", "quantity": 1, "price": 15.0},
            headers={"X-Request-Timestamp": "2026-11-23T12:00:00Z"},
        )
        self.assertEqual(resp_patch.status_code, 201)

        injector.revert("fault_004_bad_parsing")

    def test_07_fault_005_lifecycle(self):
        """Fault 5 (Orders ZeroDivisionError in unit discount) apply, symptom, revert, and patch."""
        # 1. Apply
        injector.apply("fault_005_unhandled_exception")
        import target_app.services.orders.app as orders_mod
        importlib.reload(orders_mod)
        client = TestClient(orders_mod.app, raise_server_exceptions=False)

        # Promo order with zero items triggers ZeroDivisionError -> 500
        resp_err = client.post(
            "/orders",
            json={"customer_id": "c1", "item": "mug", "quantity": 1, "price": 12.0, "promo_items": 0, "promo_discount": 5.0},
        )
        self.assertEqual(resp_err.status_code, 500)

        # 2. Revert
        injector.revert("fault_005_unhandled_exception")
        importlib.reload(orders_mod)
        client_clean = TestClient(orders_mod.app, raise_server_exceptions=False)
        resp_clean = client_clean.post(
            "/orders",
            json={"customer_id": "c1", "item": "mug", "quantity": 1, "price": 12.0, "promo_items": 0, "promo_discount": 5.0},
        )
        self.assertEqual(resp_clean.status_code, 201)

        # 3. Patch
        injector.patch("fault_005_unhandled_exception")
        importlib.reload(orders_mod)
        client_patch = TestClient(orders_mod.app, raise_server_exceptions=False)
        resp_patch = client_patch.post(
            "/orders",
            json={"customer_id": "c1", "item": "mug", "quantity": 1, "price": 12.0, "promo_items": 0, "promo_discount": 5.0},
        )
        self.assertEqual(resp_patch.status_code, 201)

        injector.revert("fault_005_unhandled_exception")

    def test_08_apply_then_revert_3x_baseline_recovery(self):
        """Task A3 Success Criteria: apply() then revert() 3 times -> error rate under 1% every time."""
        fault_ids = [
            "fault_001_bad_deploy",
            "fault_002_off_by_one",
            "fault_003_wrong_status_code",
            "fault_004_bad_parsing",
            "fault_005_unhandled_exception",
        ]

        for fid in fault_ids:
            manifest = injector.get_fault(fid)
            for cycle in range(1, 4):
                # 1. Apply
                injector.apply(fid)
                self.assertTrue(injector.status()["active"], f"Active status failed for {fid} cycle {cycle}")

                # 2. Revert
                injector.revert(fid)
                self.assertFalse(injector.status()["active"], f"Revert status failed for {fid} cycle {cycle}")
                self.assertEqual((TARGET_APP_DIR / "version.txt").read_text(encoding="utf-8").strip(), "v1.0.0")

                # 3. Verify baseline traffic error rate < 1%
                svc = manifest.target_service
                errors = 0
                total = 10

                if svc == "orders":
                    import target_app.services.orders.app as mod
                    importlib.reload(mod)
                    client = TestClient(mod.app, raise_server_exceptions=False)
                    for i in range(total):
                        r = client.post("/orders", json={"customer_id": f"c_{i}", "item": "item", "quantity": 1, "price": 10.0})
                        if r.status_code != 201:
                            errors += 1
                elif svc == "payments":
                    import target_app.services.payments.app as mod
                    importlib.reload(mod)
                    client = TestClient(mod.app, raise_server_exceptions=False)
                    for i in range(total):
                        r = client.post("/process", json={"order_id": f"ord_{i}", "amount": 50.0, "currency": "USD"})
                        if r.status_code != 200:
                            errors += 1
                elif svc == "gateway":
                    import target_app.services.gateway.app as mod
                    importlib.reload(mod)
                    client = TestClient(mod.app, raise_server_exceptions=False)
                    for i in range(total):
                        r = client.post(
                            "/api/orders",
                            json={"customer_id": f"c_{i}", "item": "item", "quantity": 1, "price": 10.0},
                            headers={"X-Request-Timestamp": "2026-11-23T10:00:00Z"},
                        )
                        if r.status_code != 201:
                            errors += 1

                err_rate = (errors / total) * 100.0
                self.assertLess(err_rate, 1.0, f"Error rate {err_rate}% exceeded 1% baseline on {fid} cycle {cycle}")

    def test_09_idempotent_revert_and_version_consistency(self):
        """Revert is safe and idempotent when called repeatedly."""
        res1 = injector.revert(record_change=False)
        self.assertEqual(res1["status"], "reverted")
        res2 = injector.revert(record_change=False)
        self.assertEqual(res2["status"], "reverted")
        self.assertFalse(injector.status()["active"])
        self.assertEqual((TARGET_APP_DIR / "version.txt").read_text(encoding="utf-8").strip(), "v1.0.0")


if __name__ == "__main__":
    unittest.main()
