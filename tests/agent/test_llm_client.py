"""Unit Tests for Person B LLM Client and Cost Accounting (Task B1).

Verifies:
1. Exact pricing calculation for Claude 3.5 Sonnet, Haiku, and Opus models.
2. Spend cap protection and SpendCapExceededError enforcement.
3. Token and cost audit logging to JSONL.
4. Usage aggregation summary.
5. Mock and Live API wrapper paths.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from agent.llm_client import (
    LLMClient,
    LLMResponse,
    SpendCapExceededError,
    calculate_cost,
    PRICING_TABLE,
)


class TestLLMClientAndPricing(unittest.TestCase):
    """Test suite for LLM Client token and cost tracking."""

    def test_01_exact_pricing_calculations(self):
        """Pricing matches Anthropic official published rates within 0.1%."""
        # Claude 3.5 Sonnet: $3.00 / MTok in, $15.00 / MTok out
        sonnet_model = "claude-3-5-sonnet-20241022"
        cost_sonnet = calculate_cost(sonnet_model, input_tokens=100_000, output_tokens=20_000)
        expected_sonnet = (100_000 / 1e6 * 3.00) + (20_000 / 1e6 * 15.00)  # 0.30 + 0.30 = 0.60
        self.assertAlmostEqual(cost_sonnet, expected_sonnet, places=5)
        self.assertEqual(cost_sonnet, 0.60)

        # Claude 3.5 Haiku: $0.80 / MTok in, $4.00 / MTok out
        haiku_model = "claude-3-5-haiku-20241022"
        cost_haiku = calculate_cost(haiku_model, input_tokens=50_000, output_tokens=10_000)
        expected_haiku = (50_000 / 1e6 * 0.80) + (10_000 / 1e6 * 4.00)  # 0.04 + 0.04 = 0.08
        self.assertAlmostEqual(cost_haiku, expected_haiku, places=5)
        self.assertEqual(cost_haiku, 0.08)

        # Claude 3 Opus: $15.00 / MTok in, $75.00 / MTok out
        opus_model = "claude-3-opus-20240229"
        cost_opus = calculate_cost(opus_model, input_tokens=10_000, output_tokens=2_000)
        expected_opus = (10_000 / 1e6 * 15.00) + (2_000 / 1e6 * 75.00)  # 0.15 + 0.15 = 0.30
        self.assertAlmostEqual(cost_opus, expected_opus, places=5)
        self.assertEqual(cost_opus, 0.30)

    def test_02_mock_call_execution(self):
        """Mock LLM call returns valid response with token counts and calculated cost."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            client = LLMClient(
                default_model="claude-3-5-sonnet-20241022",
                spend_cap=5.00,
                usage_log_path=tmp_path,
                mock=True,
            )

            resp = client.call("Explain database connection pool exhaustion.")
            self.assertIsInstance(resp, LLMResponse)
            self.assertGreater(len(resp.content), 10)
            self.assertGreater(resp.input_tokens, 0)
            self.assertGreater(resp.output_tokens, 0)
            self.assertEqual(resp.total_tokens, resp.input_tokens + resp.output_tokens)
            self.assertGreater(resp.cost_usd, 0.0)
            self.assertEqual(resp.model, "claude-3-5-sonnet-20241022")
            self.assertTrue(resp.call_id.startswith("call_"))
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_03_spend_cap_enforcement(self):
        """Client raises SpendCapExceededError when spend exceeds limit."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            # Set a spend cap ($0.05)
            client = LLMClient(
                default_model="claude-3-5-sonnet-20241022",
                spend_cap=0.05,
                usage_log_path=tmp_path,
                mock=True,
            )

            # First small call succeeds
            resp1 = client.call("Hello", max_tokens=20)
            self.assertGreater(resp1.cost_usd, 0.0)

            # Manually simulate accumulated spend reaching cap limit
            client.cumulative_cost_usd = 0.049

            # Next call estimated at > $0.002 will exceed $0.05 cap and raise SpendCapExceededError
            with self.assertRaises(SpendCapExceededError):
                client.call("Another question that exceeds spend cap", max_tokens=500)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_04_usage_ledger_audit_trail(self):
        """Usage ledger logs JSON audit records with exact token and cost details."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            client = LLMClient(
                default_model="claude-3-5-haiku-20241022",
                spend_cap=10.00,
                usage_log_path=tmp_path,
                mock=True,
            )

            resp = client.call("Summarize incident inc_001")
            self.assertTrue(tmp_path.exists())

            # Read back log line
            lines = tmp_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)

            entry = json.loads(lines[0])
            self.assertEqual(entry["call_id"], resp.call_id)
            self.assertEqual(entry["model"], "claude-3-5-haiku-20241022")
            self.assertEqual(entry["cost_usd"], resp.cost_usd)
            self.assertEqual(entry["total_tokens"], resp.total_tokens)
            self.assertEqual(entry["status"], "success")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_05_usage_summary_aggregation(self):
        """get_usage_summary correctly computes cumulative totals and remaining budget."""
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            client = LLMClient(
                default_model="claude-3-5-sonnet-20241022",
                spend_cap=5.00,
                usage_log_path=tmp_path,
                mock=True,
            )

            r1 = client.call("Test prompt 1")
            r2 = client.call("Test prompt 2")
            r3 = client.call("Test prompt 3")

            summary = client.get_usage_summary()
            self.assertEqual(summary["total_calls"], 3)
            self.assertEqual(summary["total_tokens"], r1.total_tokens + r2.total_tokens + r3.total_tokens)
            self.assertAlmostEqual(
                summary["total_cost_usd"],
                r1.cost_usd + r2.cost_usd + r3.cost_usd,
                places=5,
            )
            self.assertAlmostEqual(
                summary["remaining_budget_usd"],
                5.00 - summary["total_cost_usd"],
                places=5,
            )
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_06_live_api_wrapper_structure(self):
        """Live call wrapper accurately parses Anthropic Messages API responses."""
        mock_anthropic = MagicMock()
        mock_response = MagicMock()

        # Mock Anthropic TextBlock response
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Identified root cause: unhandled discount KeyError."
        mock_response.content = [text_block]
        mock_response.usage.input_tokens = 120
        mock_response.usage.output_tokens = 35
        mock_response.stop_reason = "end_turn"

        mock_anthropic.messages.create.return_value = mock_response

        client = LLMClient(
            api_key="sk-ant-test-live-key",
            default_model="claude-3-5-sonnet-20241022",
            mock=False,
        )
        client._anthropic_client = mock_anthropic

        resp = client.call("Analyze logs", system="You are an on-call SRE.")
        self.assertEqual(resp.content, "Identified root cause: unhandled discount KeyError.")
        self.assertEqual(resp.input_tokens, 120)
        self.assertEqual(resp.output_tokens, 35)
        self.assertEqual(resp.total_tokens, 155)

        # Check call was dispatched with extra_body temperature
        mock_anthropic.messages.create.assert_called_once()
        call_kwargs = mock_anthropic.messages.create.call_args[1]
        self.assertEqual(call_kwargs["model"], "claude-3-5-sonnet-20241022")
        self.assertEqual(call_kwargs["extra_body"], {"temperature": 0.0})


if __name__ == "__main__":
    unittest.main()
