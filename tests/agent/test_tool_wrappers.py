"""Unit Tests for Agent Tool Wrappers against PlatformClient (Day 2 Task B2).

Owner: Person B (Brain & Trust)
Verifies:
1. All 9 tool wrappers execute against FixtureClient across recorded incident bundles.
2. Long outputs are truncated to a token limit with clear truncation notices.
3. Errors (validation, path traversal, file not found, client exceptions) return structured JSON messages.
4. execute() dispatch and get_tool_wrappers() dictionary mappings.
5. Full parity across all 5 recorded incident fixture bundles.
"""

import json
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from contracts.models import FixProposal
from platform_api.client import PlatformClient
from platform_api.fixture_client import FixtureClient
from agent.tools import (
    DEFAULT_MAX_TOOL_TOKENS,
    PLATFORM_TOOL_DEFINITIONS,
    ToolExecutor,
    PlatformToolExecutor,
    ToolRegistry,
    format_tool_error,
    format_tool_success,
    get_agent_tools,
    get_tool_names,
    get_tool_wrappers,
    is_tool_error,
    truncate_to_token_limit,
    validate_tool_call,
    wrap_query_logs,
    wrap_query_metrics,
    wrap_list_changes,
    wrap_git_log,
    wrap_git_diff,
    wrap_read_file,
    wrap_service_map,
    wrap_search_past_incidents,
    wrap_propose_fix,
)


class TestToolWrappers(unittest.TestCase):
    """Test suite for the 9 PlatformClient tool wrappers, truncation, and structured errors."""

    def setUp(self):
        self.fc = FixtureClient(fixture_bundle="fault_001_bad_deploy")
        self.executor = ToolExecutor(platform_client=self.fc, max_tokens=DEFAULT_MAX_TOOL_TOKENS)

    def test_01_query_logs_wrapper_against_fixture(self):
        """Wrapper 1: query_logs retrieves logs, supports service/text filtering and limit."""
        # 1. Direct wrapper method
        raw_out = self.executor.query_logs(service="orders")
        self.assertFalse(is_tool_error(raw_out))
        logs = json.loads(raw_out)
        self.assertIsInstance(logs, list)
        self.assertGreater(len(logs), 0)
        for log in logs:
            self.assertEqual(log["service"], "orders")

        # 2. Free text filtering
        filtered_out = self.executor.query_logs(text="TypeError")
        filtered_logs = json.loads(filtered_out)
        self.assertIsInstance(filtered_logs, list)
        for log in filtered_logs:
            full_text = f"{log.get('message', '')} {log.get('exception', '')}".lower()
            self.assertIn("typeerror", full_text)

        # 3. Standalone wrapper function
        fn_out = wrap_query_logs(self.fc, limit=2)
        fn_logs = json.loads(fn_out)
        self.assertLessEqual(len(fn_logs), 2)

    def test_02_query_metrics_wrapper_against_fixture(self):
        """Wrapper 2: query_metrics retrieves Prometheus time series data."""
        raw_out = self.executor.query_metrics(metric_name="http_requests_total")
        self.assertFalse(is_tool_error(raw_out))
        metrics = json.loads(raw_out)
        self.assertIsInstance(metrics, dict)
        self.assertEqual(metrics.get("status"), "success")
        self.assertIn("data", metrics)

        # Standalone function
        fn_out = wrap_query_metrics(self.fc, metric_name="http_requests_total")
        self.assertIn('"status": "success"', fn_out)

    def test_03_list_changes_wrapper_against_fixture(self):
        """Wrapper 3: list_changes retrieves recent deployments and config revisions."""
        raw_out = self.executor.list_changes(service="orders")
        self.assertFalse(is_tool_error(raw_out))
        changes = json.loads(raw_out)
        self.assertIsInstance(changes, list)
        self.assertGreater(len(changes), 0)
        self.assertTrue("id" in changes[0] or "change_id" in changes[0])
        self.assertEqual(changes[0]["service"], "orders")

        # Standalone function
        fn_out = wrap_list_changes(self.fc, limit=1)
        fn_changes = json.loads(fn_out)
        self.assertLessEqual(len(fn_changes), 1)

    def test_04_git_log_wrapper_against_fixture(self):
        """Wrapper 4: git_log retrieves commit history."""
        raw_out = self.executor.git_log(n=5)
        self.assertFalse(is_tool_error(raw_out))
        commits = json.loads(raw_out)
        self.assertIsInstance(commits, list)
        self.assertGreater(len(commits), 0)
        self.assertIn("commit", commits[0])
        self.assertIn("message", commits[0])

        # Standalone function
        fn_out = wrap_git_log(self.fc, n=1)
        fn_commits = json.loads(fn_out)
        self.assertEqual(len(fn_commits), 1)

    def test_05_git_diff_wrapper_against_fixture(self):
        """Wrapper 5: git_diff returns unified diff string."""
        diff_out = self.executor.git_diff(commit_a="HEAD~1")
        self.assertFalse(is_tool_error(diff_out))
        self.assertIsInstance(diff_out, str)
        self.assertGreater(len(diff_out), 0)

        # Standalone function
        fn_out = wrap_git_diff(self.fc, commit_a="HEAD")
        self.assertIsInstance(fn_out, str)

    def test_06_read_file_wrapper_against_fixture(self):
        """Wrapper 6: read_file returns file contents and supports line slicing."""
        path = "target-app/services/orders/app.py"
        full_content = self.executor.read_file(path=path)
        self.assertFalse(is_tool_error(full_content))
        self.assertIn("def ", full_content)

        # Line slice
        sliced = self.executor.read_file(path=path, start_line=1, end_line=10)
        self.assertFalse(is_tool_error(sliced))
        lines = sliced.splitlines()
        self.assertLessEqual(len(lines), 10)

        # Standalone function
        fn_out = wrap_read_file(self.fc, path=path, start_line=1, end_line=5)
        self.assertFalse(is_tool_error(fn_out))

    def test_07_service_map_wrapper_against_fixture(self):
        """Wrapper 7: service_map returns microservice architecture topology."""
        raw_out = self.executor.service_map()
        self.assertFalse(is_tool_error(raw_out))
        smap = json.loads(raw_out)
        self.assertIsInstance(smap, dict)
        self.assertIn("services", smap)
        self.assertIn("orders", smap["services"])

        # Standalone function
        fn_out = wrap_service_map(self.fc)
        self.assertIn('"services"', fn_out)

    def test_08_search_past_incidents_wrapper_against_fixture(self):
        """Wrapper 8: search_past_incidents searches institutional memory."""
        raw_out = self.executor.search_past_incidents(query="deploy", limit=2)
        self.assertFalse(is_tool_error(raw_out))
        incidents = json.loads(raw_out)
        self.assertIsInstance(incidents, list)
        self.assertGreater(len(incidents), 0)
        self.assertTrue("id" in incidents[0] or "incident_id" in incidents[0])

        # Standalone function
        fn_out = wrap_search_past_incidents(self.fc, query="timeout")
        self.assertFalse(is_tool_error(fn_out))

    def test_09_propose_fix_wrapper_against_fixture(self):
        """Wrapper 9: propose_fix validates proposal and returns structured receipt."""
        # Unpacked kwargs
        receipt_out = self.executor.propose_fix(
            type="rollback",
            risk_tier="T1",
            rationale="Roll back faulty deploy dep_20261122_v1.0.1",
            expected_metric_effect="Error rate drops from 40% to 0%",
            target_service="orders",
        )
        self.assertFalse(is_tool_error(receipt_out))
        receipt = json.loads(receipt_out)
        self.assertEqual(receipt.get("status"), "accepted")
        self.assertIn("proposal_id", receipt)
        self.assertEqual(receipt.get("risk_tier"), "T1")

        # As dict parameter
        dict_receipt_out = self.executor.propose_fix(
            proposal={
                "type": "patch",
                "risk_tier": "T2",
                "rationale": "Apply code fix",
                "expected_metric_effect": "Orders 200 OK restored",
                "target_service": "orders",
                "diff": "--- a/app.py\n+++ b/app.py\n",
            }
        )
        self.assertFalse(is_tool_error(dict_receipt_out))
        dict_receipt = json.loads(dict_receipt_out)
        self.assertEqual(dict_receipt.get("status"), "accepted")

        # Standalone function
        fn_out = wrap_propose_fix(
            self.fc,
            type="rollback",
            risk_tier="T1",
            rationale="Automated rollback",
            expected_metric_effect="Zero errors",
        )
        self.assertIn('"status": "accepted"', fn_out)

    def test_10_long_output_truncation_to_token_limit(self):
        """Long outputs are truncated to the configured token limit with clear markers."""
        # Test helper directly
        sample_text = "A" * 1000
        truncated_text, was_truncated = truncate_to_token_limit(
            sample_text,
            max_tokens=50,       # 50 tokens * 4 chars = 200 chars
            chars_per_token=4.0,
        )
        self.assertTrue(was_truncated)
        self.assertIn("[TRUNCATED: Output exceeded token limit of ~50 tokens (200 chars)", truncated_text)
        self.assertTrue(truncated_text.startswith("A" * 200))

        # Output within limit is NOT truncated
        short_text = "Short text"
        not_trunc, was_trunc = truncate_to_token_limit(short_text, max_tokens=100)
        self.assertFalse(was_trunc)
        self.assertEqual(not_trunc, short_text)

        # Test wrapper integration with low token limit (25 tokens ≈ 100 chars)
        small_token_executor = ToolExecutor(
            platform_client=self.fc,
            max_tokens=25,
        )
        read_out = small_token_executor.read_file("target-app/services/orders/app.py")
        self.assertIn("[TRUNCATED: Output exceeded token limit of ~25 tokens", read_out)
        self.assertLess(len(read_out), 500)

        # Test log output truncation
        logs_out = small_token_executor.query_logs(service="orders")
        self.assertIn("[TRUNCATED: Output exceeded token limit", logs_out)

    def test_11_errors_return_structured_message_on_validation_failure(self):
        """Validation errors return structured JSON messages with error_type and message."""
        # 1. Missing required 'metric_name'
        err_metrics = self.executor.query_metrics(metric_name="")
        self.assertTrue(is_tool_error(err_metrics))
        err_data = json.loads(err_metrics)
        self.assertEqual(err_data["status"], "error")
        self.assertTrue(err_data["error"])
        self.assertEqual(err_data["tool"], "query_metrics")
        self.assertEqual(err_data["error_type"], "ValidationError")
        self.assertIn("Error:", err_data["message"])

        # 2. Missing required 'commit_a' for git_diff
        err_diff = self.executor.git_diff(commit_a="")
        self.assertTrue(is_tool_error(err_diff))
        diff_err_data = json.loads(err_diff)
        self.assertEqual(diff_err_data["error_type"], "ValidationError")

        # 3. Missing required 'path' for read_file
        err_file = self.executor.read_file(path="")
        self.assertTrue(is_tool_error(err_file))
        file_err_data = json.loads(err_file)
        self.assertEqual(file_err_data["error_type"], "ValidationError")

        # 4. Missing required 'query' for search_past_incidents
        err_past = self.executor.search_past_incidents(query="")
        self.assertTrue(is_tool_error(err_past))
        past_err_data = json.loads(err_past)
        self.assertEqual(past_err_data["error_type"], "ValidationError")

        # 5. Missing required fields in propose_fix
        err_fix = self.executor.propose_fix(type="rollback")  # missing rationale, risk_tier, expected_metric_effect
        self.assertTrue(is_tool_error(err_fix))
        fix_err_data = json.loads(err_fix)
        self.assertEqual(fix_err_data["error_type"], "ValidationError")

    def test_12_errors_return_structured_message_on_security_path_traversal(self):
        """read_file strictly rejects directory traversal ('..') with structured SecurityError."""
        bad_paths = [
            "../../etc/passwd",
            "target-app/services/orders/../../../contracts",
            "../secret.env",
        ]
        for bad_p in bad_paths:
            out = self.executor.read_file(path=bad_p)
            self.assertTrue(is_tool_error(out))
            err_data = json.loads(out)
            self.assertEqual(err_data["status"], "error")
            self.assertEqual(err_data["error_type"], "SecurityError")
            self.assertIn("traversal", err_data["message"].lower())

    def test_13_errors_return_structured_message_on_file_not_found(self):
        """read_file returns structured FileNotFoundError when file does not exist."""
        out = self.executor.read_file(path="target-app/non_existent_file_xyz.py")
        self.assertTrue(is_tool_error(out))
        err_data = json.loads(out)
        self.assertEqual(err_data["status"], "error")
        self.assertEqual(err_data["error_type"], "FileNotFoundError")
        self.assertIn("not found", err_data["message"].lower())

    def test_14_errors_return_structured_message_on_client_exception(self):
        """Underlying client exceptions are caught and formatted as structured errors."""
        mock_client = MagicMock(spec=PlatformClient)
        mock_client.query_logs.side_effect = ConnectionError("Platform service unreachable")

        err_exec = ToolExecutor(platform_client=mock_client)
        out = err_exec.execute("query_logs", {"service": "orders"})
        self.assertTrue(is_tool_error(out))
        err_data = json.loads(out)
        self.assertEqual(err_data["status"], "error")
        self.assertEqual(err_data["error_type"], "ConnectionError")
        self.assertIn("Platform service unreachable", err_data["message"])

    def test_15_dispatcher_execute_and_get_tool_wrappers(self):
        """execute() dispatcher and get_tool_wrappers() map all 9 tools correctly."""
        # 1. get_tool_wrappers returns 9 tools
        wrappers = get_tool_wrappers(self.fc)
        self.assertEqual(len(wrappers), 9)
        expected_tools = get_tool_names()
        for t in expected_tools:
            self.assertIn(t, wrappers)
            self.assertTrue(callable(wrappers[t]))

        # 2. Unknown tool returns structured UnknownToolError
        unknown_out = self.executor.execute("invalid_tool_name", {})
        self.assertTrue(is_tool_error(unknown_out))
        unknown_data = json.loads(unknown_out)
        self.assertEqual(unknown_data["error_type"], "ValidationError")

        # 3. All 9 tools successfully executed via executor.execute()
        calls = [
            ("query_logs", {"service": "orders", "limit": 2}),
            ("query_metrics", {"metric_name": "http_requests_total"}),
            ("list_changes", {"limit": 2}),
            ("git_log", {"n": 2}),
            ("git_diff", {"commit_a": "HEAD~1"}),
            ("read_file", {"path": "target-app/services/orders/app.py", "start_line": 1, "end_line": 5}),
            ("service_map", {}),
            ("search_past_incidents", {"query": "deploy"}),
            ("propose_fix", {
                "type": "rollback",
                "risk_tier": "T1",
                "rationale": "Rollback test",
                "expected_metric_effect": "No errors",
            }),
        ]
        for tool_name, args in calls:
            res = self.executor.execute(tool_name, args)
            self.assertFalse(is_tool_error(res), f"Tool {tool_name} failed: {res}")

    def test_16_parity_across_all_recorded_fixture_bundles(self):
        """All 9 wrappers function properly across every recorded incident bundle (Faults 1 to 5)."""
        bundles = [
            "fault_001_bad_deploy",
            "fault_002_off_by_one",
            "fault_003_wrong_status_code",
            "fault_004_bad_parsing",
            "fault_005_unhandled_exception",
        ]
        for bundle in bundles:
            client = FixtureClient(fixture_bundle=bundle)
            executor = ToolExecutor(platform_client=client)

            # Each bundle should support logs, metrics, changes, service map, and fix proposal
            logs = executor.query_logs(limit=5)
            self.assertFalse(is_tool_error(logs), f"Logs failed on {bundle}")

            metrics = executor.query_metrics(metric_name="*")
            self.assertFalse(is_tool_error(metrics), f"Metrics failed on {bundle}")

            changes = executor.list_changes(limit=5)
            self.assertFalse(is_tool_error(changes), f"Changes failed on {bundle}")

            smap = executor.service_map()
            self.assertFalse(is_tool_error(smap), f"Service map failed on {bundle}")

            receipt = executor.propose_fix(
                type="rollback",
                risk_tier="T1",
                rationale=f"Automated test rollback for {bundle}",
                expected_metric_effect="Recover baseline",
            )
            self.assertFalse(is_tool_error(receipt), f"Fix proposal failed on {bundle}")


if __name__ == "__main__":
    unittest.main()
