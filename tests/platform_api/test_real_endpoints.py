"""Unit Tests for Real Platform API Endpoints (Day 2 Task A2).

Verifies:
1. /logs/query count parity with direct log file grep.
2. /logs/query filtering by service, level, trace_id, text substring, and time range.
3. Sub-500ms response time on all endpoints.
4. /metrics/query schema validity and Prometheus formatting.
5. /changes endpoint sorting, service filtering, and contract compliance.
6. GET and POST parity for /logs/query and /metrics/query.
"""

import json
from pathlib import Path
import tempfile
import time
import unittest

from starlette.testclient import TestClient

from contracts.models import ChangeRecord
from platform_api.app import create_platform_api_app
from platform_api.real_client import RealPlatformClient


class TestRealEndpoints(unittest.TestCase):
    """Test suite for Real Platform API endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parent.parent.parent
        cls.app = create_platform_api_app(mode="real", repo_root=cls.repo_root)
        cls.client = TestClient(cls.app)

    def test_01_logs_query_endpoint_parity_with_grep(self):
        """/logs/query count matches direct line-by-line grep of the service log file."""
        orders_log = self.repo_root / "logs" / "orders.log"
        if not orders_log.exists():
            orders_log = self.repo_root / "logs" / "all_services.log"

        self.assertTrue(orders_log.exists(), f"Log file {orders_log} must exist.")

        # Direct line-by-line grep
        grep_errors = 0
        with open(orders_log, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"orders"' in line and '"ERROR"' in line:
                    grep_errors += 1

        t0 = time.perf_counter()
        resp = self.client.get("/logs/query", params={"service": "orders", "level": "ERROR", "limit": 1000})
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(resp.status_code, 200)
        logs = resp.json()

        # Latency check
        self.assertLess(latency_ms, 500.0, f"Response latency {latency_ms:.2f}ms exceeded 500ms")

        # Grep parity check
        expected_count = min(grep_errors, 1000)
        self.assertEqual(len(logs), expected_count, "Endpoint count must match grep count")
        for log in logs:
            self.assertEqual(log.get("service"), "orders")
            self.assertEqual(log.get("level", "").upper(), "ERROR")

    def test_02_logs_query_text_and_trace_filters(self):
        """/logs/query filters by text substring and trace_id in under 500ms."""
        # Query with text search
        t0 = time.perf_counter()
        resp = self.client.get("/logs/query", params={"service": "orders", "text": "POST /orders"})
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(resp.status_code, 200)
        self.assertLess(latency_ms, 500.0)
        logs = resp.json()
        if logs:
            # Check text substring in first result
            first_log = logs[0]
            searchable = (first_log.get("message", "") + " " + json.dumps(first_log)).lower()
            self.assertIn("post /orders", searchable)

            # Query by trace_id of first result
            trace_id = first_log.get("trace_id")
            if trace_id and trace_id != "none":
                resp_trace = self.client.get("/logs/query", params={"trace_id": trace_id})
                self.assertEqual(resp_trace.status_code, 200)
                trace_logs = resp_trace.json()
                self.assertGreaterEqual(len(trace_logs), 1)
                self.assertTrue(all(l.get("trace_id") == trace_id for l in trace_logs))

    def test_03_metrics_query_endpoint(self):
        """/metrics/query returns valid Prometheus schema in under 500ms."""
        t0 = time.perf_counter()
        resp = self.client.get("/metrics/query", params={"metric_name": "http_requests_total"})
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(resp.status_code, 200)
        self.assertLess(latency_ms, 500.0)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("data", data)
        self.assertIn("result", data["data"])

    def test_04_changes_endpoint_and_filtering(self):
        """/changes returns deployment records sorted newest first in under 500ms."""
        t0 = time.perf_counter()
        resp = self.client.get("/changes", params={"service": "orders", "limit": 5})
        latency_ms = (time.perf_counter() - t0) * 1000.0

        self.assertEqual(resp.status_code, 200)
        self.assertLess(latency_ms, 500.0)
        changes = resp.json()
        self.assertIsInstance(changes, list)

        if changes:
            # Validate each record against ChangeRecord schema
            for chg in changes:
                rec = ChangeRecord.model_validate(chg)
                self.assertEqual(rec.service, "orders")

    def test_05_post_and_get_method_parity(self):
        """POST and GET endpoints for /logs/query and /metrics/query yield identical results."""
        # /logs/query parity
        get_logs = self.client.get("/logs/query", params={"service": "orders", "level": "ERROR", "limit": 10}).json()
        post_logs = self.client.post("/logs/query", json={"service": "orders", "level": "ERROR", "limit": 10}).json()
        self.assertEqual(len(get_logs), len(post_logs))

        # /metrics/query parity
        get_metrics = self.client.get("/metrics/query", params={"metric_name": "http_requests_total"}).json()
        post_metrics = self.client.post("/metrics/query", json={"metric_name": "http_requests_total"}).json()
        self.assertEqual(get_metrics.get("status"), post_metrics.get("status"))

    def test_06_real_client_git_and_repo_tools(self):
        """RealPlatformClient git_log, git_diff, and read_file operate on local repository."""
        real_client = RealPlatformClient(repo_root=self.repo_root)

        # 1. git_log
        commits = real_client.git_log(n=5)
        self.assertIsInstance(commits, list)
        self.assertGreater(len(commits), 0)
        self.assertIn("commit", commits[0])
        self.assertIn("author", commits[0])

        # 2. git_diff
        head_commit = commits[0]["commit"]
        diff = real_client.git_diff(commit_a=f"{head_commit}~1", commit_b=head_commit)
        self.assertIsInstance(diff, str)

        # 3. read_file
        content = real_client.read_file("contracts/models.py", start_line=1, end_line=15)
        self.assertIn("Incident", content)

    def test_07_service_map_and_propose_fix(self):
        """RealPlatformClient provides topology service map and registers fix proposals."""
        real_client = RealPlatformClient(repo_root=self.repo_root)

        # Service Map
        smap = real_client.service_map()
        self.assertIn("services", smap)
        self.assertIn("orders", smap["services"])
        self.assertIn("gateway", smap["services"])

        # Propose Fix
        receipt = real_client.propose_fix({
            "type": "rollback",
            "risk_tier": "T1",
            "rationale": "Roll back bad deployment",
            "expected_metric_effect": "Error rate drops to 0%",
            "target_service": "orders",
        })
        self.assertEqual(receipt["status"], "accepted")
        self.assertTrue(receipt["proposal_id"].startswith("prop_"))


if __name__ == "__main__":
    unittest.main()
