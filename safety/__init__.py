"""safety component package.

Owner: Person B
Architecture Section 6 & Day 5 Task B1
"""

from safety.gate import (
    ActionRequest,
    DEFAULT_ALLOWED_PATH_PREFIXES,
    DEFAULT_ALLOWED_SERVICES,
    GateDecision,
    PolicyEvaluation,
    RiskTier,
    SafetyGate,
    extract_paths_from_diff,
)

__all__ = [
    "ActionRequest",
    "DEFAULT_ALLOWED_PATH_PREFIXES",
    "DEFAULT_ALLOWED_SERVICES",
    "GateDecision",
    "PolicyEvaluation",
    "RiskTier",
    "SafetyGate",
    "extract_paths_from_diff",
]
