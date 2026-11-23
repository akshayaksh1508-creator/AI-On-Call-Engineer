"""Unit Tests for Run Logger and Partial RunRecord (Day 2 Task B4).

Owner: Person B (Brain & Trust)
Verifies:
1. RunLogger accurately captures tokens, cost, tool calls, and wall time.
2. Logged totals match API usage within 2% (Task B4 core requirement).
3. PartialRunRecord converts cleanly to contracts.models.RunRecord.
4. Persistence to individual JSON and aggregate JSONL log files.
5. Integration with InvestigationLoop.
6. Day 2 End-of-Day Gate: reads incident, executes investigation loop, returns valid Hypothesis, and logs RunRecord.
"""

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from contracts.models import Incident, RunRecord
from agent.llm_client import LLMClient, LLMResponse, calculate_cost, DEFAULT_MODEL
from agent.loop import InvestigationLoop, InvestigationResult
from agent.run_logger import (
    PartialRunRecord,
    RunLogger,
    load_run_records,
)
from platform_api.fixture_client import FixtureClient


class TestRunLogger(unittest.TestCase):
    """Test suite for RunLogger and PartialRunRecord."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_dir = Path(self.temp_dir.name) / "runs"
        self.jsonl_path = Path(self.temp_dir.name) / "run_records.jsonl"
        self.logger = RunLogger(
            incident_id="inc_test_001",
            fault_id="fault_001_bad_deploy",
            log_dir=self.log_dir,
            jsonl_path=self.jsonl_path,
            auto_write=False,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_run_logger_records_llm_and_tool_calls(self):
        """RunLogger tracks tokens, costs, tool calls, and breakdown per step."""
        self.logger.start(incident_id="inc_001", fault_id="fault_001")

        # Record LLM call 1
        resp1 = LLMResponse(
            content="Thinking...",
            model=DEFAULT_MODEL,
            input_tokens=500,
            output_tokens=100,
            total_tokens=600,
            cost_usd=calculate_cost(DEFAULT_MODEL, 500, 100),
            cumulative_cost_usd=calculate_cost(DEFAULT_MODEL, 500, 100),
            latency_seconds=0.45,
            tool_calls=[{"name": "query_logs", "input": {"service": "orders"}}],
        )
        self.logger.record_llm_call(resp1, step=1)

        # Record Tool call 1
        self.logger.record_tool_call(
            tool_name="query_logs",
            arguments={"service": "orders"},
            output_length=1200,
            duration_seconds=0.05,
            is_error=False,
            step=1,
        )

        # Record Tool call 2
        self.logger.record_tool_call(
            tool_name="list_changes",
            arguments={"service": "orders"},
            output_length=400,
            duration_seconds=0.03,
            is_error=False,
            step=1,
        )

        # Record LLM call 2 (final diagnosis)
        resp2 = LLMResponse(
            content="Diagnosis JSON",
            model=DEFAULT_MODEL,
            input_tokens=1500,
            output_tokens=300,
            total_tokens=1800,
            cost_usd=calculate_cost(DEFAULT_MODEL, 1500, 300),
            cumulative_cost_usd=calculate_cost(DEFAULT_MODEL, 2000, 400),
            latency_seconds=0.85,
        )
        self.logger.record_llm_call(resp2, step=2)

        record = self.logger.finish(status="completed")

        self.assertEqual(record.incident_id, "inc_001")
        self.assertEqual(record.fault_id, "fault_001")
        self.assertEqual(record.prompt_tokens, 2000)
        self.assertEqual(record.completion_tokens, 400)
        self.assertEqual(record.tokens, 2400)
        self.assertAlmostEqual(record.cost_usd, resp1.cost_usd + resp2.cost_usd, places=5)
        self.assertEqual(record.tool_calls, 2)
        self.assertEqual(record.tool_breakdown, {"query_logs": 1, "list_changes": 1})
        self.assertEqual(record.steps, 2)
        self.assertEqual(record.status, "completed")
        self.assertGreater(record.wall_time, 0.0)

    def test_02_logged_totals_match_api_usage_within_2_percent(self):
        """Task B4 Acceptance Criteria: Logged totals match actual API usage within 2%."""
        self.logger.start(incident_id="inc_002", fault_id="fault_002")

        # Simulate 5 multi-turn LLM calls with realistic variations
        api_actual_input = 0
        api_actual_output = 0
        api_actual_tokens = 0
        api_actual_cost = 0.0

        token_steps = [
            (800, 150),
            (1450, 220),
            (2100, 310),
            (3200, 450),
            (4100, 600),
        ]

        for step, (in_tok, out_tok) in enumerate(token_steps, start=1):
            tot = in_tok + out_tok
            c = calculate_cost(DEFAULT_MODEL, in_tok, out_tok)

            api_actual_input += in_tok
            api_actual_output += out_tok
            api_actual_tokens += tot
            api_actual_cost += c

            resp = LLMResponse(
                content=f"Step {step} text",
                model=DEFAULT_MODEL,
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=tot,
                cost_usd=c,
                cumulative_cost_usd=api_actual_cost,
                latency_seconds=0.2,
            )
            self.logger.record_llm_call(resp, step=step)

        record = self.logger.finish(status="completed")

        # 1. Direct equality check
        self.assertEqual(record.tokens, api_actual_tokens)
        self.assertAlmostEqual(record.cost_usd, api_actual_cost, places=5)

        # 2. Strict tolerance verification: within 2% (0.02)
        is_accurate, token_err_pct, cost_err_pct = self.logger.verify_accuracy(
            actual_tokens=api_actual_tokens,
            actual_cost_usd=api_actual_cost,
            tolerance=0.02,
        )

        self.assertTrue(is_accurate, "Logged totals must be within 2% of API usage")
        self.assertLessEqual(token_err_pct, 2.0)
        self.assertLessEqual(cost_err_pct, 2.0)

    def test_03_partial_run_record_converts_to_contract_run_record(self):
        """PartialRunRecord converts to schema-valid contracts.models.RunRecord."""
        partial = PartialRunRecord(
            incident_id="inc_conv_001",
            fault_id="fault_003_currency_bug",
            t_detect=12.5,
            t_rca=4.25,
            tokens=3500,
            cost_usd=0.0245,
            tool_calls=4,
            wall_time=4.25,
            steps=3,
        )

        contract_rec = partial.to_contract_run_record()

        self.assertIsInstance(contract_rec, RunRecord)
        self.assertEqual(contract_rec.incident_id, "inc_conv_001")
        self.assertEqual(contract_rec.fault_id, "fault_003_currency_bug")
        self.assertEqual(contract_rec.t_detect, 12.5)
        self.assertEqual(contract_rec.t_rca, 4.25)
        self.assertEqual(contract_rec.t_fix, 0.0)
        self.assertEqual(contract_rec.t_verified, 0.0)
        self.assertEqual(contract_rec.tokens, 3500)
        self.assertEqual(contract_rec.cost_usd, 0.0245)
        self.assertFalse(contract_rec.unsafe)

    def test_04_file_persistence_json_and_jsonl(self):
        """Writes detailed individual JSON runs and appends to aggregate JSONL stream."""
        logger_persistence = RunLogger(
            incident_id="inc_persist_001",
            fault_id="fault_001",
            log_dir=self.log_dir,
            jsonl_path=self.jsonl_path,
            auto_write=True,
        )

        # Run 1
        resp = LLMResponse(
            content="Summary",
            model=DEFAULT_MODEL,
            input_tokens=1000,
            output_tokens=200,
            total_tokens=1200,
            cost_usd=calculate_cost(DEFAULT_MODEL, 1000, 200),
            cumulative_cost_usd=0.006,
            latency_seconds=0.3,
        )
        logger_persistence.record_llm_call(resp, step=1)
        logger_persistence.record_tool_call("query_logs", {"service": "orders"})
        rec1 = logger_persistence.finish(status="completed")

        # Verify individual JSON was written
        json_files = list(self.log_dir.glob("*.json"))
        self.assertEqual(len(json_files), 1)

        with open(json_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["record"]["incident_id"], "inc_persist_001")
        self.assertEqual(len(data["llm_calls"]), 1)
        self.assertEqual(len(data["tool_calls"]), 1)

        # Run 2 on same JSONL stream
        logger_persistence.start(incident_id="inc_persist_002", fault_id="fault_002")
        logger_persistence.record_llm_call(resp, step=1)
        rec2 = logger_persistence.finish(status="completed")

        # Verify JSONL contains both records
        records = load_run_records(self.jsonl_path)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["incident_id"], "inc_persist_001")
        self.assertEqual(records[1]["incident_id"], "inc_persist_002")

    def test_05_investigation_loop_automatic_telemetry_logging(self):
        """InvestigationLoop automatically logs RunRecord matching LLMClient usage."""
        fc = FixtureClient(fixture_bundle="fault_001_bad_deploy")
        llm = LLMClient(mock=True)

        loop = InvestigationLoop(
            llm_client=llm,
            platform_client=fc,
            log_runs=False,  # Test in-memory record generation
        )

        incident = Incident(
            id="inc_loop_test_001",
            service="orders",
            started_at="2026-11-23T10:00:00Z",
            symptoms=["500 Internal Server Error"],
        )

        res = loop.run(incident)

        self.assertIsInstance(res, InvestigationResult)
        self.assertIsNotNone(res.run_record, "InvestigationResult must contain run_record")
        self.assertIsNotNone(res.partial_run_record, "InvestigationResult must contain partial_run_record")
        self.assertIsInstance(res.run_record, RunRecord)
        self.assertIsInstance(res.partial_run_record, PartialRunRecord)

        # Verify metrics consistency
        self.assertEqual(res.run_record.tokens, res.tokens)
        self.assertEqual(res.run_record.cost_usd, res.cost_usd)
        self.assertEqual(res.partial_run_record.tool_calls, res.tool_calls_count)
        self.assertGreater(res.run_record.t_rca, 0.0)

    def test_06_day2_end_of_day_gate_live_diagnosis_and_run_record(self):
        """Day 2 End-of-Day Gate: The agent reads an incident from Platform API,

        returns a valid Hypothesis with cited evidence, and records a RunRecord
        matching usage within 2%.
        """
        fc = FixtureClient(fixture_bundle="fault_001_bad_deploy")
        llm = LLMClient(mock=True)

        loop = InvestigationLoop(
            llm_client=llm,
            platform_client=fc,
            log_runs=True,
            run_logger=RunLogger(
                incident_id="inc_eod_001",
                fault_id="fault_001_bad_deploy",
                log_dir=self.log_dir,
                jsonl_path=self.jsonl_path,
            ),
        )

        incident = fc.get_incident()
        res = loop.run(incident)

        # Gate Condition 1: Valid Hypothesis produced
        self.assertGreater(len(res.hypotheses), 0, "Gate requires valid Hypothesis output")
        top_hyp = res.hypotheses[0]
        self.assertIn(top_hyp.category, ("code", "config", "resource", "cross_service", "dependency", "unknown"))
        self.assertGreaterEqual(top_hyp.confidence, 0.0)
        self.assertLessEqual(top_hyp.confidence, 1.0)
        self.assertGreater(len(top_hyp.evidence_ids), 0, "Hypothesis must cite evidence IDs")

        # Gate Condition 2: Valid Evidence objects present
        self.assertGreater(len(res.evidence), 0, "Must have cited Evidence objects")

        inc_id = incident["id"] if isinstance(incident, dict) else incident.id

        # Gate Condition 3: RunRecord generated with accurate token/cost accounting
        self.assertIsNotNone(res.run_record)
        self.assertEqual(res.run_record.incident_id, inc_id)
        self.assertEqual(res.run_record.tokens, res.tokens)
        self.assertEqual(res.run_record.cost_usd, res.cost_usd)

        # Gate Condition 4: JSON and JSONL records persisted
        json_files = list(self.log_dir.glob("*.json"))
        self.assertGreaterEqual(len(json_files), 1)
        jsonl_records = load_run_records(self.jsonl_path)
        self.assertEqual(len(jsonl_records), 1)
        self.assertEqual(jsonl_records[0]["incident_id"], inc_id)


if __name__ == "__main__":
    unittest.main()
