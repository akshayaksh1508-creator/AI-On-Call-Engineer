"""safety component package.

Owner: Person B
Architecture Section 6 & Day 5 Tasks B1, B2
"""

from safety.approval import (
    ApprovalDecision,
    ApprovalSession,
    ApprovalStatus,
    HumanApprovalManager,
)
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
    "ApprovalDecision",
    "ApprovalSession",
    "ApprovalStatus",
    "DEFAULT_ALLOWED_PATH_PREFIXES",
    "DEFAULT_ALLOWED_SERVICES",
    "GateDecision",
    "HumanApprovalManager",
    "PolicyEvaluation",
    "RiskTier",
    "SafetyGate",
    "extract_paths_from_diff",
]
