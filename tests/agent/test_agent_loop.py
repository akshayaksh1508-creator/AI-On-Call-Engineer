"""Unit Tests for Agent Tool-Use Reasoning Loop (Day 2 Task B1).

Owner: Person B (Brain & Trust)
Verifies:
1. Normal tool execution and hypothesis completion within budget.
2. Step budget enforcement: strictly halts when step budget (15) is exhausted.
3. Resilient tool error handling: catches tool exceptions and feeds error messages back to the LLM without crashing.
4. Malformed JSON handling: triggers exactly one repair retry and recovers.
5. Double malformed JSON failure: cleanly escalates without infinite looping.
6. Per-call retry with exponential backoff on transient failure.
7. End-to-end integration with FixtureClient and token/cost accounting.
"""

import json
from pathlib import Path
import unittest

from contracts import Incident, load_fixture_bundle
from platform_api import FixtureClient
from agent.llm_client import LLMClient, LLMResponse, calculate_cost
from agent.loop import InvestigationLoop, AgentLoop, InvestigationResult

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def make_mock_response(
    content: str = "",
    tool_calls: list = None,
    stop_reason: str = "end_turn",
) -> LLMResponse:
    """Helper to construct deterministic LLMResponse objects."""
    tools = tool_calls or []
    in_tok = max(len(content.split()) + 20, 30)
    out_tok = max(len(content.split()) + 10, 20)
    cost = calculate_cost("claude-3-5-sonnet-20241022", in_tok, out_tok)
    return LLMResponse(
        content=content,
        model="claude-3-5-sonnet-20241022",
        input_tokens=in_tok,
        output_tokens=out_tok,
        total_tokens=in_tok + out_tok,
        cost_usd=cost,
        cumulative_cost_usd=cost,
        latency_seconds=0.01,
        stop_reason=stop_reason,
        tool_calls=tools,
    )


VALID_DIAGNOSIS_JSON = json.dumps({
    "investigation_summary": "Identified null pointer in discount calculation following deployment v1.0.1.",
    "evidence": [
        {
            "id": "ev_log_001",
            "type": "log",
            "ref": "target-app/services/orders/main.py:42",
            "excerpt": "TypeError: 'NoneType' object is not subscriptable",
            "ts": "2026-11-22T21:40:00Z"
        },
        {
            "id": "ev_change_001",
            "type": "config",
            "ref": "dep_20261122_v1.0.1",
            "excerpt": "Deploy v1.0.1 commit c0ffee14a",
            "ts": "2026-11-22T21:38:00Z"
        }
    ],
    "hypotheses": [
        {
            "cause": "Unhandled NoneType in discount calculation introduced in commit c0ffee14a [ev_log_001] [ev_change_001]",
            "category": "code",
            "confidence": 0.95,
            "evidence_ids": ["ev_log_001", "ev_change_001"],
            "culprit_change": "dep_20261122_v1.0.1"
        }
    ],
    "uncited_claims": [],
    "recommended_action": "propose_fix",
    "escalation_reason": None
})


class TestAgentLoop(unittest.TestCase):
    """Test suite for Agent Investigation Loop (Task B1)."""

    def setUp(self):
        self.fc = FixtureClient(fixture_bundle="fault_001_bad_deploy")
        self.incident = Incident(**self.fc.get_incident())

    def test_01_loop_normal_completion(self):
        """Loop executes tool calls, updates context, and completes with valid diagnosis."""
        llm = LLMClient(mock=True)

        # Turn 1: LLM calls list_changes
        # Turn 2: LLM calls query_logs
        # Turn 3: LLM provides valid diagnosis JSON
        llm.mock_queue = [
            make_mock_response(
                tool_calls=[{
                    "id": "tc_1",
                    "name": "list_changes",
                    "input": {"service": "orders"}
                }],
                stop_reason="tool_use",
            ),
            make_mock_response(
                tool_calls=[{
                    "id": "tc_2",
                    "name": "query_logs",
                    "input": {"service": "orders", "level": "ERROR"}
                }],
                stop_reason="tool_use",
            ),
            make_mock_response(
                content=VALID_DIAGNOSIS_JSON,
                stop_reason="end_turn",
            ),
        ]

        loop = InvestigationLoop(
            llm_client=llm,
            platform_client=self.fc,
            step_budget=15,
        )
        res = loop.run(self.incident)

        self.assertEqual(res.status, "completed")
        self.assertEqual(res.steps_taken, 2)
        self.assertEqual(res.tool_calls_count, 2)
        self.assertEqual(len(res.hypotheses), 1)
        self.assertEqual(res.hypotheses[0].confidence, 0.95)
        self.assertEqual(res.hypotheses[0].culprit_change, "dep_20261122_v1.0.1")
        self.assertEqual(len(res.evidence), 2)
        self.assertFalse(res.repaired_json)
        self.assertGreater(res.tokens, 0)
        self.assertGreater(res.cost_usd, 0.0)

    def test_02_loop_step_budget_enforcement(self):
        """Loop strictly halts when the 15-step budget is reached without completing."""
        llm = LLMClient(mock=True)

        # Queue 20 consecutive tool calls (exceeding budget of 15)
        llm.mock_queue = [
            make_mock_response(
                tool_calls=[{
                    "id": f"tc_{i}",
                    "name": "list_changes",
                    "input": {"service": "orders"}
                }],
                stop_reason="tool_use",
            )
            for i in range(20)
        ]

        loop = InvestigationLoop(
            llm_client=llm,
            platform_client=self.fc,
            step_budget=15,
        )
        res = loop.run(self.incident)

        # Loop must stop at 15 steps
        self.assertEqual(res.status, "budget_exhausted")
        self.assertEqual(res.steps_taken, 15)
        self.assertIn("budget", res.escalation_reason.lower())

    def test_03_loop_handles_tool_error(self):
        """Loop catches tool errors, formats structured messages, and continues cleanly."""
        llm = LLMClient(mock=True)

        # Turn 1: LLM calls an invalid tool / tool with bad arguments
        # Turn 2: LLM receives error message in context and provides final diagnosis
        llm.mock_queue = [
            make_mock_response(
                tool_calls=[{
                    "id": "tc_err",
                    "name": "non_existent_tool",
                    "input": {"foo": "bar"}
                }],
                stop_reason="tool_use",
            ),
            make_mock_response(
                content=VALID_DIAGNOSIS_JSON,
                stop_reason="end_turn",
            ),
        ]

        loop = InvestigationLoop(
            llm_client=llm,
            platform_client=self.fc,
            step_budget=15,
        )
        res = loop.run(self.incident)

        self.assertEqual(res.status, "completed")
        self.assertEqual(res.steps_taken, 1)
        self.assertTrue(res.tool_call_history[0]["is_error"])
        self.assertIn("Error:", res.tool_call_history[0]["output_preview"])

    def test_04_loop_handles_malformed_json_with_one_repair_retry(self):
        """Loop detects malformed JSON, prompts one repair retry, and recovers on valid response."""
        llm = LLMClient(mock=True)

        # Turn 1: LLM returns corrupted/malformed JSON
        # Turn 2 (Repair retry): LLM returns valid structured JSON
        malformed_json = "Here is my diagnosis: { 'cause': unclosed string, 'confidence': 0.9"

        llm.mock_queue = [
            make_mock_response(content=malformed_json, stop_reason="end_turn"),
            make_mock_response(content=VALID_DIAGNOSIS_JSON, stop_reason="end_turn"),
        ]

        loop = InvestigationLoop(
            llm_client=llm,
            platform_client=self.fc,
            step_budget=15,
        )
        res = loop.run(self.incident)

        self.assertEqual(res.status, "completed")
        self.assertTrue(res.repaired_json, "repaired_json flag must be True")
        self.assertEqual(len(res.hypotheses), 1)
        self.assertEqual(res.hypotheses[0].confidence, 0.95)

    def test_05_loop_handles_double_malformed_json_and_escalates(self):
        """Loop halts and escalates if JSON repair retry also fails."""
        llm = LLMClient(mock=True)

        bad_text_1 = "This is not JSON at all."
        bad_text_2 = "Still not JSON despite repair prompt."

        llm.mock_queue = [
            make_mock_response(content=bad_text_1, stop_reason="end_turn"),
            make_mock_response(content=bad_text_2, stop_reason="end_turn"),
        ]

        loop = InvestigationLoop(
            llm_client=llm,
            platform_client=self.fc,
            step_budget=15,
        )
        res = loop.run(self.incident)

        self.assertEqual(res.status, "escalated")
        self.assertTrue(res.repaired_json)
        self.assertIn("repair retry", res.escalation_reason)
        self.assertEqual(res.recommended_action, "escalate")

    def test_06_per_call_retry_on_transient_failure(self):
        """_call_llm_with_retry recovers when the first call raises a transient error."""
        llm = LLMClient(mock=True)
        call_count = 0

        def flaky_handler(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionResetError("Simulated network drop")
            return make_mock_response(content=VALID_DIAGNOSIS_JSON)

        llm.mock_handler = flaky_handler

        loop = InvestigationLoop(
            llm_client=llm,
            platform_client=self.fc,
            max_retries=2,
        )
        res = loop.run(self.incident)

        self.assertEqual(res.status, "completed")
        self.assertEqual(call_count, 2, "Must have retried exactly once after transient drop")

    def test_07_full_fixture_run_end_to_end(self):
        """Loop runs end-to-end with default mock responder and FixtureClient."""
        llm = LLMClient(mock=True)
        loop = AgentLoop(
            llm_client=llm,
            platform_client=self.fc,
            step_budget=15,
        )
        res = loop.run(self.incident)

        self.assertEqual(res.incident_id, self.incident.id)
        self.assertEqual(res.service, "orders")
        self.assertEqual(res.status, "completed")
        self.assertGreater(len(res.hypotheses), 0)
        self.assertGreater(res.tokens, 0)
        self.assertGreater(res.cost_usd, 0.0)


if __name__ == "__main__":
    unittest.main()
