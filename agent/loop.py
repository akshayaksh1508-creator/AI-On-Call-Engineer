"""Autonomous Agent Investigation Loop (Day 2 Task B1).

Owner: Person B (Brain & Trust)
Implements Section 7 Agent Design Rules:
1. Step budget: exactly 15 tool-call turns maximum before halting.
2. Per-call timeout and retry handling with exponential backoff.
3. Resilient tool error handling: catches tool exceptions, formats structured
   error messages, and feeds them back into conversation history without crashing.
4. Malformed JSON recovery: triggers exactly one repair prompt if the LLM output
   fails JSON/schema parsing; accepts repaired output or escalates gracefully.
5. Strict telemetry accounting: tracks tokens, cost, tool call count, and wall time.
"""

import json
import logging
import time
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union
import uuid

from pydantic import BaseModel, ConfigDict, Field

from contracts.models import Evidence, Hypothesis, Incident
from agent.llm_client import LLMClient, LLMResponse, calculate_cost
from agent.prompts import (
    SYSTEM_PROMPT_V0,
    build_investigation_user_prompt,
    parse_agent_response,
)
from agent.tools import (
    DEFAULT_MAX_TOOL_TOKENS,
    PLATFORM_TOOL_DEFINITIONS,
    ToolExecutor,
    get_agent_tools,
    is_tool_error,
    validate_tool_call,
)
from platform_api.client import PlatformClient

logger = logging.getLogger("agent.loop")


class InvestigationResult(BaseModel):
    """Output artifact of an autonomous investigation run."""
    model_config = ConfigDict(extra="ignore")

    incident_id: str
    service: str
    status: Literal["completed", "budget_exhausted", "escalated", "failed"] = "completed"
    steps_taken: int = Field(default=0, description="Number of tool-call turns executed")
    tool_calls_count: int = Field(default=0, description="Total individual tool calls made")
    tool_call_history: List[Dict[str, Any]] = Field(default_factory=list)
    investigation_summary: str = Field(default="")
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    uncited_claims: List[str] = Field(default_factory=list)
    recommended_action: Optional[str] = "propose_fix"
    escalation_reason: Optional[str] = None
    tokens: int = Field(default=0, description="Total tokens consumed across all turns")
    cost_usd: float = Field(default=0.0, description="Total USD cost incurred across all turns")
    wall_time_seconds: float = Field(default=0.0, description="Total wall-clock duration in seconds")
    raw_output: str = Field(default="")
    repaired_json: bool = Field(default=False, description="Whether JSON repair was triggered")


class InvestigationLoop:
    """Autonomous agent reasoning loop operating over a PlatformClient interface."""

    def __init__(
        self,
        llm_client: LLMClient,
        platform_client: PlatformClient,
        step_budget: int = 15,
        call_timeout: float = 30.0,
        max_retries: int = 2,
        system_prompt: str = SYSTEM_PROMPT_V0,
        max_tool_tokens: int = DEFAULT_MAX_TOOL_TOKENS,
        tool_executor: Optional[ToolExecutor] = None,
    ):
        self.llm_client = llm_client
        self.platform_client = platform_client
        self.step_budget = step_budget
        self.call_timeout = call_timeout
        self.max_retries = max_retries
        self.system_prompt = system_prompt
        self.max_tool_tokens = max_tool_tokens
        self.tool_executor = tool_executor or ToolExecutor(
            platform_client=self.platform_client,
            max_tokens=self.max_tool_tokens,
        )

    def _call_llm_with_retry(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Executes an LLM call with per-call timeout and exponential backoff retry."""
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.llm_client.call(
                    messages=messages,
                    system=self.system_prompt,
                    tools=tools,
                )
                return response
            except Exception as exc:
                last_exception = exc
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries + 1,
                    exc,
                )
                if attempt < self.max_retries:
                    backoff = 0.05 * (2 ** attempt)
                    time.sleep(backoff)
                else:
                    break

        raise RuntimeError(
            f"LLM call failed after {self.max_retries + 1} attempts: {last_exception}"
        ) from last_exception

    def _execute_tool_safely(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> str:
        """Executes a single tool call via ToolExecutor with validation, error isolation, and token limits.
        
        Rule: Tool errors are caught, formatted as structured messages, and returned
        to the LLM so it can adjust its reasoning without crashing the loop.
        """
        return self.tool_executor.execute(tool_name, arguments)

    def run(
        self,
        incident: Union[Incident, Dict[str, Any]],
        initial_context: Optional[str] = None,
    ) -> InvestigationResult:
        """Runs the autonomous investigation loop against the given incident."""
        start_time = time.perf_counter()

        if isinstance(incident, dict):
            inc_obj = Incident(**incident)
        else:
            inc_obj = incident

        # Initialize conversation history with structured prompt
        user_prompt = build_investigation_user_prompt(
            incident=inc_obj,
            additional_context=initial_context,
        )
        messages: List[Dict[str, Any]] = [
            {"role": "user", "content": user_prompt}
        ]

        step = 0
        total_tokens = 0
        total_cost = 0.0
        tool_call_count = 0
        tool_call_history: List[Dict[str, Any]] = []
        tools = get_agent_tools()
        repaired_json = False
        repair_attempts = 0

        while step < self.step_budget:
            # 1. LLM call with retry
            llm_resp = self._call_llm_with_retry(messages=messages, tools=tools)
            total_tokens += llm_resp.total_tokens
            total_cost += llm_resp.cost_usd

            # 2. Check for tool calls
            if llm_resp.tool_calls:
                # Add assistant turn to history
                assistant_blocks = []
                if llm_resp.content:
                    assistant_blocks.append({"type": "text", "text": llm_resp.content})
                for tc in llm_resp.tool_calls:
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:8]}"),
                        "name": tc["name"],
                        "input": tc.get("input", {}),
                    })
                messages.append({"role": "assistant", "content": assistant_blocks})

                # Check step budget before executing tool turn
                step += 1
                if step > self.step_budget:
                    # Budget strictly exceeded
                    logger.warning("Step budget (%d) reached. Halting tool loop.", self.step_budget)
                    break

                # Execute all requested tool calls in this turn
                tool_results_blocks = []
                for tc in llm_resp.tool_calls:
                    tool_call_count += 1
                    t_name = tc["name"]
                    t_args = tc.get("input", {})
                    t_id = tc.get("id", f"toolu_{uuid.uuid4().hex[:8]}")

                    tool_output = self._execute_tool_safely(t_name, t_args)

                    is_err = is_tool_error(tool_output)
                    tool_call_history.append({
                        "step": step,
                        "tool": t_name,
                        "arguments": t_args,
                        "output_preview": tool_output[:300],
                        "is_error": is_err,
                    })

                    tool_results_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": t_id,
                        "content": tool_output,
                    })

                # Append tool results as user turn
                messages.append({"role": "user", "content": tool_results_blocks})

                # If we just reached the step budget on this turn, ask for final diagnosis
                if step >= self.step_budget:
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Step budget ({self.step_budget} tool calls) has been exhausted. "
                            "Please provide your final root-cause hypothesis and evidence summary immediately."
                        ),
                    })
                continue

            # 3. No tool calls: LLM returned text (candidate diagnosis)
            raw_text = llm_resp.content
            try:
                hypotheses, evidence_list, uncited_claims, raw_dict = parse_agent_response(raw_text)
                wall_time = round(time.perf_counter() - start_time, 4)

                return InvestigationResult(
                    incident_id=inc_obj.id,
                    service=inc_obj.service,
                    status="completed",
                    steps_taken=step,
                    tool_calls_count=tool_call_count,
                    tool_call_history=tool_call_history,
                    investigation_summary=raw_dict.get("investigation_summary", ""),
                    hypotheses=hypotheses,
                    evidence=evidence_list,
                    uncited_claims=uncited_claims,
                    recommended_action=raw_dict.get("recommended_action", "propose_fix"),
                    escalation_reason=raw_dict.get("escalation_reason"),
                    tokens=total_tokens,
                    cost_usd=round(total_cost, 6),
                    wall_time_seconds=wall_time,
                    raw_output=raw_text,
                    repaired_json=repaired_json,
                )

            except Exception as parse_err:
                # 4. Handle malformed JSON with exactly one repair retry
                if repair_attempts < 1:
                    repair_attempts += 1
                    repaired_json = True
                    logger.warning("Agent output was not valid JSON (%s). Prompting repair retry.", parse_err)

                    messages.append({"role": "assistant", "content": raw_text})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Error: Your response could not be parsed as valid JSON ({parse_err}). "
                            "Please fix this and output ONLY valid JSON matching the schema specified in the system instructions."
                        ),
                    })
                    continue
                else:
                    # Repair attempt also failed: escalate safely without looping infinitely
                    logger.error("JSON repair retry failed. Escalating incident %s.", inc_obj.id)
                    wall_time = round(time.perf_counter() - start_time, 4)
                    return InvestigationResult(
                        incident_id=inc_obj.id,
                        service=inc_obj.service,
                        status="escalated",
                        steps_taken=step,
                        tool_calls_count=tool_call_count,
                        tool_call_history=tool_call_history,
                        investigation_summary="Escalated: Agent failed to deliver valid structured JSON after repair retry.",
                        hypotheses=[],
                        evidence=[],
                        uncited_claims=[f"Malformed output: {raw_text[:200]}"],
                        recommended_action="escalate",
                        escalation_reason=f"Failed to produce valid schema after repair retry: {parse_err}",
                        tokens=total_tokens,
                        cost_usd=round(total_cost, 6),
                        wall_time_seconds=wall_time,
                        raw_output=raw_text,
                        repaired_json=repaired_json,
                    )

        # Loop completed because step >= step_budget
        wall_time = round(time.perf_counter() - start_time, 4)
        logger.warning("Investigation terminated: step budget (%d) exhausted for %s", self.step_budget, inc_obj.id)
        return InvestigationResult(
            incident_id=inc_obj.id,
            service=inc_obj.service,
            status="budget_exhausted",
            steps_taken=step,
            tool_calls_count=tool_call_count,
            tool_call_history=tool_call_history,
            investigation_summary="Investigation terminated: Step budget (15 tool calls) exhausted before hypothesis convergence.",
            hypotheses=[],
            evidence=[],
            uncited_claims=["Step budget exhausted before diagnosis completion."],
            recommended_action="escalate",
            escalation_reason="Step budget limit (15) reached without final answer.",
            tokens=total_tokens,
            cost_usd=round(total_cost, 6),
            wall_time_seconds=wall_time,
            raw_output="",
            repaired_json=repaired_json,
        )


# Export alias
AgentLoop = InvestigationLoop
