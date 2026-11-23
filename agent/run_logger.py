"""Run Logger and Telemetry Tracker for Partial RunRecords.

Owner: Person B (Brain & Trust)
Fulfills Day 2 Task B4:
1. Tracks exact LLM tokens, USD costs, tool call counts, and wall time during an investigation.
2. Emits PartialRunRecord instances and serializes them to JSON and JSONL.
3. Converts cleanly to contracts.models.RunRecord for benchmark compatibility.
4. Verifies that logged totals match API usage within 2%.
5. Supports Day 2 End-of-Day gate: recording autonomous incident diagnosis telemetry.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from contracts.models import RunRecord
from agent.llm_client import LLMResponse, calculate_cost, PRICING_TABLE, DEFAULT_MODEL

logger = logging.getLogger("nightshift.agent.run_logger")

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOGS_DIR = ROOT_DIR / "logs" / "runs"
DEFAULT_JSONL_PATH = ROOT_DIR / "logs" / "run_records.jsonl"


class PartialRunRecord(BaseModel):
    """Telemetry and benchmark record captured during the RCA/Investigation stage."""
    model_config = ConfigDict(extra="ignore")

    incident_id: str = Field(..., description="Unique incident identifier, e.g. inc_20261122_001")
    fault_id: str = Field(default="unknown", description="Fault ID or ground-truth catalogue ID")
    t_detect: float = Field(default=0.0, description="Seconds from fault injection to detection (0.0 if not measured)")
    t_rca: float = Field(default=0.0, description="Seconds spent in root cause analysis")
    t_fix: float = Field(default=0.0, description="Seconds spent in fix generation (0.0 for Day 2)")
    t_verified: float = Field(default=0.0, description="Seconds spent in verification (0.0 for Day 2)")
    rca_correct_top1: bool = Field(default=False, description="Did top-1 hypothesis match ground truth?")
    rca_correct_top3: bool = Field(default=False, description="Did top-3 hypotheses contain ground truth?")
    fix_ok: bool = Field(default=False, description="Did remediation recover health?")
    unsafe: bool = Field(default=False, description="Did action violate safety constraints?")
    tokens: int = Field(default=0, description="Total prompt and completion tokens consumed")
    cost_usd: float = Field(default=0.0, description="Calculated API cost in USD")

    # Detailed operational telemetry
    prompt_tokens: int = Field(default=0, description="Total input/prompt tokens")
    completion_tokens: int = Field(default=0, description="Total output/completion tokens")
    tool_calls: int = Field(default=0, description="Total tool invocations made")
    tool_breakdown: Dict[str, int] = Field(default_factory=dict, description="Invocation count by tool name")
    wall_time: float = Field(default=0.0, description="Total wall-clock duration in seconds")
    steps: int = Field(default=0, description="Number of agent turns/steps executed")
    status: str = Field(default="completed", description="Outcome status (completed, escalated, budget_exhausted)")
    repaired_json: bool = Field(default=False, description="Whether JSON repair retry was triggered")
    model: str = Field(default=DEFAULT_MODEL, description="LLM model identifier used")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_contract_run_record(self) -> RunRecord:
        """Convert partial record into the shared contracts.models.RunRecord schema."""
        return RunRecord(
            incident_id=self.incident_id,
            fault_id=self.fault_id,
            t_detect=round(self.t_detect, 4),
            t_rca=round(self.t_rca, 4),
            t_fix=round(self.t_fix, 4),
            t_verified=round(self.t_verified, 4),
            rca_correct_top1=self.rca_correct_top1,
            rca_correct_top3=self.rca_correct_top3,
            fix_ok=self.fix_ok,
            unsafe=self.unsafe,
            tokens=self.tokens,
            cost_usd=round(self.cost_usd, 6),
        )


class RunLogger:
    """Manages telemetry collection, cost accounting, and persistence for incident runs."""

    def __init__(
        self,
        incident_id: str = "unknown",
        fault_id: str = "unknown",
        log_dir: Optional[Union[str, Path]] = None,
        jsonl_path: Optional[Union[str, Path]] = None,
        auto_write: bool = True,
    ):
        self.incident_id = incident_id
        self.fault_id = fault_id
        self.log_dir = Path(log_dir) if log_dir else DEFAULT_LOGS_DIR
        self.jsonl_path = Path(jsonl_path) if jsonl_path else DEFAULT_JSONL_PATH
        self.auto_write = auto_write

        # Accumulated metrics
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_tokens: int = 0
        self.total_cost_usd: float = 0.0
        self.tool_calls_count: int = 0
        self.tool_breakdown: Dict[str, int] = {}
        self.steps_count: int = 0
        self.model_used: str = DEFAULT_MODEL
        self.repaired_json: bool = False

        # Call histories
        self.llm_call_history: List[Dict[str, Any]] = []
        self.tool_call_history: List[Dict[str, Any]] = []

        # Timing
        self._start_perf: float = time.perf_counter()
        self._end_perf: Optional[float] = None
        self._start_iso: str = datetime.now(timezone.utc).isoformat()
        self._end_iso: Optional[str] = None

    def start(self, incident_id: Optional[str] = None, fault_id: Optional[str] = None) -> None:
        """Reset and start telemetry timer for a new run."""
        if incident_id:
            self.incident_id = incident_id
        if fault_id:
            self.fault_id = fault_id
        self._start_perf = time.perf_counter()
        self._end_perf = None
        self._start_iso = datetime.now(timezone.utc).isoformat()
        self._end_iso = None

    def record_llm_call(
        self,
        response: LLMResponse,
        step: int = 0,
        call_type: str = "investigation_turn",
    ) -> None:
        """Record an LLM call's token count, cost, and latency."""
        self.total_prompt_tokens += response.input_tokens
        self.total_completion_tokens += response.output_tokens
        self.total_tokens += response.total_tokens
        self.total_cost_usd += response.cost_usd
        self.model_used = response.model
        if step > self.steps_count:
            self.steps_count = step

        entry = {
            "step": step,
            "call_type": call_type,
            "call_id": response.call_id,
            "model": response.model,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "total_tokens": response.total_tokens,
            "cost_usd": response.cost_usd,
            "latency_seconds": round(response.latency_seconds, 4),
            "tool_calls_requested": len(response.tool_calls),
            "stop_reason": response.stop_reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.llm_call_history.append(entry)

    def record_tool_call(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        output_length: int = 0,
        duration_seconds: float = 0.0,
        is_error: bool = False,
        step: int = 0,
    ) -> None:
        """Record a platform tool invocation."""
        self.tool_calls_count += 1
        self.tool_breakdown[tool_name] = self.tool_breakdown.get(tool_name, 0) + 1

        entry = {
            "step": step,
            "tool": tool_name,
            "arguments": arguments or {},
            "output_length_chars": output_length,
            "duration_seconds": round(duration_seconds, 4),
            "is_error": is_error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.tool_call_history.append(entry)

    def finish(
        self,
        status: str = "completed",
        repaired_json: bool = False,
        fault_id: Optional[str] = None,
        t_detect: float = 0.0,
    ) -> PartialRunRecord:
        """Finalize timing and return a populated PartialRunRecord."""
        if self._end_perf is None:
            self._end_perf = time.perf_counter()
            self._end_iso = datetime.now(timezone.utc).isoformat()

        if fault_id:
            self.fault_id = fault_id

        self.repaired_json = self.repaired_json or repaired_json
        wall_time = max(0.0001, self._end_perf - self._start_perf)

        record = PartialRunRecord(
            incident_id=self.incident_id,
            fault_id=self.fault_id,
            t_detect=t_detect,
            t_rca=round(wall_time, 4),
            t_fix=0.0,
            t_verified=0.0,
            rca_correct_top1=False,
            rca_correct_top3=False,
            fix_ok=False,
            unsafe=False,
            tokens=self.total_tokens,
            cost_usd=round(self.total_cost_usd, 6),
            prompt_tokens=self.total_prompt_tokens,
            completion_tokens=self.total_completion_tokens,
            tool_calls=self.tool_calls_count,
            tool_breakdown=dict(self.tool_breakdown),
            wall_time=round(wall_time, 4),
            steps=self.steps_count,
            status=status,
            repaired_json=self.repaired_json,
            model=self.model_used,
            timestamp=self._end_iso or datetime.now(timezone.utc).isoformat(),
        )

        if self.auto_write:
            try:
                self.write_run_record(record)
            except Exception as e:
                logger.error("Failed to write run record automatically: %s", e)

        return record

    def write_run_record(
        self,
        record: Optional[PartialRunRecord] = None,
        output_file: Optional[Union[str, Path]] = None,
        append_jsonl: bool = True,
    ) -> Path:
        """Write record to individual JSON file and optionally append to run_records.jsonl."""
        rec = record or self.finish()

        # Ensure directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

        if output_file:
            json_path = Path(output_file)
        else:
            safe_ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            json_path = self.log_dir / f"run_{rec.incident_id}_{safe_ts}.json"

        # Write detailed run payload
        payload = {
            "record": rec.model_dump(),
            "contract_run_record": rec.to_contract_run_record().model_dump(),
            "llm_calls": self.llm_call_history,
            "tool_calls": self.tool_call_history,
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

        # Append to JSONL stream for benchmark metrics aggregation
        if append_jsonl:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec.model_dump()) + "\n")

        return json_path

    def verify_accuracy(
        self,
        actual_tokens: int,
        actual_cost_usd: float,
        tolerance: float = 0.02,
    ) -> Tuple[bool, float, float]:
        """Verify that logged totals match actual API usage within tolerance (default 2%).

        Returns:
            (is_within_tolerance, token_error_percentage, cost_error_percentage)
        """
        # Token accuracy check
        if actual_tokens > 0:
            token_err = abs(self.total_tokens - actual_tokens) / float(actual_tokens)
        else:
            token_err = 0.0 if self.total_tokens == 0 else 1.0

        # Cost accuracy check
        if actual_cost_usd > 0.0:
            cost_err = abs(self.total_cost_usd - actual_cost_usd) / float(actual_cost_usd)
        else:
            cost_err = 0.0 if self.total_cost_usd == 0.0 else 1.0

        is_accurate = (token_err <= tolerance) and (cost_err <= tolerance)
        return is_accurate, round(token_err * 100.0, 2), round(cost_err * 100.0, 2)


def load_run_records(jsonl_path: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """Load all records from the aggregate JSONL file."""
    path = Path(jsonl_path) if jsonl_path else DEFAULT_JSONL_PATH
    if not path.exists():
        return []

    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
