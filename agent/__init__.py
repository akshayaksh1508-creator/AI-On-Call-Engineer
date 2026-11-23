"""agent component package.

Owner: Person B (Brain & Trust)
Provides the autonomous investigator LLM client, prompt templates, and reasoning loops.
"""

from agent.llm_client import (
    LLMClient,
    LLMResponse,
    SpendCapExceededError,
    calculate_cost,
    PRICING_TABLE,
)

__all__ = [
    "LLMClient",
    "LLMResponse",
    "SpendCapExceededError",
    "calculate_cost",
    "PRICING_TABLE",
]
