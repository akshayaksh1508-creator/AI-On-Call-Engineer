"""agent component package.

Owner: Person B (Brain & Trust)
Provides the autonomous investigator LLM client, prompt templates, JSON tool schemas, and reasoning loops.
"""

from agent.llm_client import (
    LLMClient,
    LLMResponse,
    SpendCapExceededError,
    calculate_cost,
    PRICING_TABLE,
)
from agent.prompts import (
    SYSTEM_PROMPT_V0,
    build_investigation_user_prompt,
    parse_agent_response,
    extract_json_from_llm_text,
)
from agent.tools import (
    PLATFORM_TOOL_DEFINITIONS,
    get_agent_tools,
    get_tool_names,
    validate_tool_call,
)

__all__ = [
    "LLMClient",
    "LLMResponse",
    "SpendCapExceededError",
    "calculate_cost",
    "PRICING_TABLE",
    "SYSTEM_PROMPT_V0",
    "build_investigation_user_prompt",
    "parse_agent_response",
    "extract_json_from_llm_text",
    "PLATFORM_TOOL_DEFINITIONS",
    "get_agent_tools",
    "get_tool_names",
    "validate_tool_call",
]
