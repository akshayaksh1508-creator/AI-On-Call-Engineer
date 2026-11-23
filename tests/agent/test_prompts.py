"""Unit Tests for Agent System Prompt v0 and 9 JSON Tool Schemas (Task B3).

Verifies:
1. System Prompt v0 enforces all Section 7 rules (loop, recent changes, service map, evidence citations).
2. JSON tool schemas match Person A's 9 PlatformClient tools.
3. User prompt formatting for incidents and log excerpts.
4. Parsing and validation of agent diagnostic output into Hypothesis and Evidence models.
5. Strict citation enforcement (uncited claims flagged as guesses).
"""

import json
import unittest
from contracts.models import Evidence, Hypothesis, Incident
from agent.prompts import (
    SYSTEM_PROMPT_V0,
    build_investigation_user_prompt,
    extract_json_from_llm_text,
    parse_agent_response,
)
from agent.tools import (
    PLATFORM_TOOL_DEFINITIONS,
    get_agent_tools,
    get_tool_names,
    validate_tool_call,
)
from agent.llm_client import LLMClient


class TestAgentPromptsAndTools(unittest.TestCase):
    """Test suite for System Prompt v0 and JSON Tool definitions."""

    def test_01_system_prompt_v0_section_7_rules(self):
        """SYSTEM_PROMPT_V0 contains all core rules from Section 7."""
        prompt = SYSTEM_PROMPT_V0.lower()

        # Rule 1: Operating loop
        self.assertIn("reasoning loop", prompt)
        self.assertIn("observe", prompt)
        self.assertIn("hypothesize", prompt)
        self.assertIn("stop", prompt)

        # Rule 2: Recent changes first
        self.assertIn("recent changes", prompt)
        self.assertIn("30 minutes", prompt)

        # Rule 3: Service map upstream rule
        self.assertIn("service map", prompt)
        self.assertIn("upstream", prompt)

        # Rule 4: Strict evidence citation rule
        self.assertIn("evidence id", prompt)
        self.assertIn("guess", prompt)

        # Rule 5: Ranked top-3 hypotheses with confidence
        self.assertIn("top-3", prompt)
        self.assertIn("confidence", prompt)

        # Rule 6: Escalation on low confidence
        self.assertIn("escalat", prompt)

    def test_02_nine_platform_tools_schema_match(self):
        """JSON tools match the 9 tools from PlatformClient with valid schemas."""
        tools = get_agent_tools()
        self.assertEqual(len(tools), 9)

        expected_tool_names = [
            "query_logs",
            "query_metrics",
            "list_changes",
            "git_log",
            "git_diff",
            "read_file",
            "service_map",
            "search_past_incidents",
            "propose_fix",
        ]
        actual_names = get_tool_names()
        self.assertEqual(actual_names, expected_tool_names)

        # Validate structure of each tool definition
        for tool in tools:
            self.assertIn("name", tool)
            self.assertIn("description", tool)
            self.assertIn("input_schema", tool)
            schema = tool["input_schema"]
            self.assertEqual(schema.get("type"), "object")
            self.assertIsInstance(schema.get("properties"), dict)
            self.assertIsInstance(schema.get("required"), list)

    def test_03_tool_call_argument_validation(self):
        """validate_tool_call validates required parameters and types."""
        # Valid call to query_logs
        valid, err = validate_tool_call("query_logs", {"service": "orders", "limit": 50})
        self.assertTrue(valid)
        self.assertIsNone(err)

        # Missing required parameter in read_file (path is required)
        valid, err = validate_tool_call("read_file", {})
        self.assertFalse(valid)
        self.assertIn("Missing required parameter 'path'", err)

        # Invalid type for limit in list_changes
        valid, err = validate_tool_call("list_changes", {"limit": "not_an_int"})
        self.assertFalse(valid)
        self.assertIn("must be an integer", err)

        # Unknown tool name
        valid, err = validate_tool_call("unknown_tool", {})
        self.assertFalse(valid)
        self.assertIn("Unknown tool", err)

    def test_04_build_investigation_user_prompt(self):
        """build_investigation_user_prompt formats incident metadata and log text."""
        incident = Incident(
            id="inc_test_001",
            service="payments",
            started_at="2026-11-22T21:40:00Z",
            symptoms=["Payment timeout rate > 10%"],
            alerts=["PaymentsTimeoutSpike"],
            recent_changes=["dep_test_v1"],
            status="open",
        )
        prompt = build_investigation_user_prompt(
            incident=incident,
            log_excerpt="[ERROR] Connection to Stripe gateway timed out after 5.0s",
            recent_changes_summary="dep_test_v1 deployed at 21:35Z",
        )
        self.assertIn("inc_test_001", prompt)
        self.assertIn("payments", prompt)
        self.assertIn("Payment timeout rate > 10%", prompt)
        self.assertIn("Connection to Stripe gateway timed out", prompt)
        self.assertIn("dep_test_v1", prompt)

    def test_05_parse_agent_response_valid(self):
        """parse_agent_response converts structured JSON into valid Hypothesis and Evidence models."""
        sample_json = {
            "investigation_summary": "Orders service crashed due to KeyError on discount.",
            "evidence": [
                {
                    "id": "ev_log_001",
                    "type": "log",
                    "ref": "target-app/services/orders/main.py:42",
                    "excerpt": "KeyError: 'code'",
                    "ts": "2026-11-22T21:40:02Z",
                }
            ],
            "hypotheses": [
                {
                    "cause": "KeyError accessing discount code [ev_log_001].",
                    "category": "code",
                    "confidence": 0.92,
                    "evidence_ids": ["ev_log_001"],
                    "culprit_change": "dep_v1",
                },
                {
                    "cause": "Database connection leak.",
                    "category": "resource",
                    "confidence": 0.15,
                    "evidence_ids": [],
                    "culprit_change": None,
                },
            ],
            "uncited_claims": [],
        }

        # Test direct JSON text
        hypotheses, evidence_list, uncited, raw = parse_agent_response(json.dumps(sample_json))
        self.assertEqual(len(hypotheses), 2)
        self.assertEqual(len(evidence_list), 1)
        self.assertIsInstance(hypotheses[0], Hypothesis)
        self.assertIsInstance(evidence_list[0], Evidence)
        self.assertEqual(evidence_list[0].id, "ev_log_001")
        self.assertEqual(hypotheses[0].confidence, 0.92)

        # Hypothesis 2 had no evidence_ids, should be flagged as guess
        self.assertTrue(any("[GUESS]" in c for c in uncited))

        # Test markdown code block fenced JSON
        fenced_text = f"Here is my diagnostic report:\n```json\n{json.dumps(sample_json)}\n```\nEnd of report."
        hyp_fenced, ev_fenced, uncited_fenced, _ = parse_agent_response(fenced_text)
        self.assertEqual(len(hyp_fenced), 2)
        self.assertEqual(len(ev_fenced), 1)

    def test_06_unreferenced_evidence_id_detection(self):
        """Citing an unknown evidence ID is flagged in uncited_claims."""
        bad_json = {
            "investigation_summary": "Test summary",
            "evidence": [],
            "hypotheses": [
                {
                    "cause": "Claim citing phantom evidence.",
                    "category": "code",
                    "confidence": 0.8,
                    "evidence_ids": ["ev_non_existent"],
                    "culprit_change": None,
                }
            ],
        }
        hypotheses, evidence, uncited, _ = parse_agent_response(json.dumps(bad_json))
        self.assertTrue(any("[UNREFERENCED]" in c for c in uncited))

    def test_07_end_to_end_prompt_and_llm_execution(self):
        """End-to-end execution with LLMClient produces validated ranked hypotheses with citations."""
        client = LLMClient(spend_cap=1.00, mock=True)
        user_prompt = build_investigation_user_prompt(
            log_excerpt="[ERROR] orders TypeError: 'NoneType' object is not subscriptable at main.py:42",
        )
        tools = get_agent_tools()

        resp = client.call(
            prompt=user_prompt,
            system=SYSTEM_PROMPT_V0,
            tools=tools,
        )

        hypotheses, evidence_list, uncited, raw = parse_agent_response(resp.content)
        self.assertGreaterEqual(len(hypotheses), 1)
        self.assertGreaterEqual(len(evidence_list), 1)

        # Top hypothesis must cite evidence
        top_hyp = hypotheses[0]
        self.assertGreater(len(top_hyp.evidence_ids), 0)
        self.assertGreater(top_hyp.confidence, 0.5)

        # Verify all cited evidence IDs exist
        ev_ids = {e.id for e in evidence_list}
        for eid in top_hyp.evidence_ids:
            self.assertIn(eid, ev_ids)


if __name__ == "__main__":
    unittest.main()
