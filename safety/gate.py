"""Safety Gate enforcing risk tiers, confidence thresholds, rate limits, allowlists, and kill switch.

Owner: Person B
Architecture Section 6 & Day 5 Task B1
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, List, Optional, Set, Tuple, Union

from contracts.models import FixProposal, Hypothesis


class RiskTier(str, Enum):
    """Risk tier classifications according to Architecture Section 6."""
    T0 = "T0"  # Read logs, metrics, code, history (always automatic)
    T1 = "T1"  # Roll back deploy / revert config change (automatic if conf >= 0.8)
    T2 = "T2"  # Code patch (automatic only in demo env if conf >= 0.85)
    T3 = "T3"  # Data, migrations, secrets, infra deletion (NEVER automatic; always human approval)


class GateDecision(str, Enum):
    """Decision produced by the safety gate."""
    AUTOMATIC = "AUTOMATIC"                              # Auto-execution approved
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"  # Requires explicit human approval
    REJECTED = "REJECTED"                                # Blocked / rejected due to policy violation or kill switch


@dataclass
class ActionRequest:
    """Request evaluated by the safety gate."""
    incident_id: str
    action_type: str  # "read", "rollback", "patch", "config", "migration", "data", "infra"
    target_service: Optional[str] = "orders"
    risk_tier: Optional[RiskTier] = None
    confidence: float = 1.0
    diff: Optional[str] = None
    affected_paths: Optional[List[str]] = None
    environment: str = "demo"  # "demo", "production", "staging"
    rationale: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyEvaluation:
    """Structured evaluation output from SafetyGate."""
    decision: GateDecision
    risk_tier: RiskTier
    reason: str
    allowed: bool  # True iff decision == GateDecision.AUTOMATIC
    requires_approval: bool  # True iff decision == GateDecision.HUMAN_APPROVAL_REQUIRED
    violations: List[str] = field(default_factory=list)
    incident_id: str = ""
    evaluated_at: float = field(default_factory=time.time)


_GIT_DIFF_PATHS = re.compile(r"^diff --git a/(.+) b/(.+)$")
_DIFF_HEADER_A = re.compile(r"^---\s+(?:a/)?(.+)$")
_DIFF_HEADER_B = re.compile(r"^\+\+\+\s+(?:b/)?(.+)$")

DEFAULT_ALLOWED_SERVICES = frozenset({
    "orders",
    "payments",
    "gateway",
    "inventory",
    "target-app",
    "orders_db",
})

DEFAULT_ALLOWED_PATH_PREFIXES = (
    "services/",
    "app/",
    "target-app/",
    "orders/",
    "payments/",
    "gateway/",
    "inventory/",
    "config/",
    "tests/",
    "src/",
)

FORBIDDEN_PATH_PATTERNS = (
    r"\.\.",                         # Directory traversal
    r"^/etc/",                       # System configuration
    r"^\.ssh/",                      # SSH credentials
    r"\.env(?:\..+)?$",              # Secrets / environment variables
    r"(?:id_rsa|private_key|token)", # Cryptographic keys
    r"password|credential|secret",   # Secret files
)

T3_PATH_PATTERNS = (
    r"migrations?/",                 # Database migrations
    r"\.sql$",                       # SQL scripts
    r"alembic/",                     # Database schema migrations
    r"docker-compose.*\.ya?ml$",     # Infrastructure files
    r"(?:k8s|kubernetes)/",          # Kubernetes infra
    r"terraform/|\.tf$",             # Terraform infra
)


def extract_paths_from_diff(diff: str) -> List[str]:
    """Extract affected file paths from a unified git diff."""
    paths: list[str] = []
    if not diff or not diff.strip():
        return paths

    for line in diff.splitlines():
        match = _GIT_DIFF_PATHS.match(line)
        if match:
            old_p, new_p = match.groups()
            paths.append(new_p.strip())
            continue

        match_b = _DIFF_HEADER_B.match(line)
        if match_b:
            p = match_b.group(1).strip()
            if p != "/dev/null":
                paths.append(p)

    return list(dict.fromkeys(paths))


class SafetyGate:
    """Safety Gate enforcing risk tiers, confidence thresholds, rate limits, allowlists, and kill switch."""

    def __init__(
        self,
        cooldown_seconds: float = 600.0,
        t1_confidence_threshold: float = 0.80,
        t2_confidence_threshold: float = 0.85,
        allowed_services: Optional[Iterable[str]] = None,
        allowed_path_prefixes: Optional[Iterable[str]] = None,
        kill_switch_path: Optional[Union[str, Path]] = None,
        demo_mode: bool = True,
    ) -> None:
        self.cooldown_seconds = float(cooldown_seconds)
        self.t1_confidence_threshold = float(t1_confidence_threshold)
        self.t2_confidence_threshold = float(t2_confidence_threshold)
        self.allowed_services: Set[str] = (
            set(allowed_services) if allowed_services is not None else set(DEFAULT_ALLOWED_SERVICES)
        )
        self.allowed_path_prefixes: Tuple[str, ...] = (
            tuple(allowed_path_prefixes) if allowed_path_prefixes is not None else DEFAULT_ALLOWED_PATH_PREFIXES
        )
        self.kill_switch_path: Optional[Path] = Path(kill_switch_path) if kill_switch_path else None
        self.demo_mode = demo_mode

        self._kill_switch_active: bool = False
        self._kill_switch_reason: str = ""
        self._incident_history: dict[str, list[float]] = {}

    # -------------------------------------------------------------------------
    # Kill Switch Management
    # -------------------------------------------------------------------------

    def trip_kill_switch(self, reason: str = "Manual kill switch engaged") -> None:
        """Globally trip the kill switch."""
        self._kill_switch_active = True
        self._kill_switch_reason = reason

    def reset_kill_switch(self) -> None:
        """Reset the programmatic kill switch."""
        self._kill_switch_active = False
        self._kill_switch_reason = ""

    def is_kill_switch_active(self) -> bool:
        """Check if kill switch is tripped via memory, env var, or file."""
        if self._kill_switch_active:
            return True

        env_val = os.getenv("NIGHTSHIFT_KILL_SWITCH", "").lower().strip()
        if env_val in ("1", "true", "yes", "on"):
            return True

        if self.kill_switch_path and self.kill_switch_path.is_file():
            return True

        return False

    # -------------------------------------------------------------------------
    # Rate Limiting & Cooldown Management
    # -------------------------------------------------------------------------

    def check_rate_limit(self, incident_id: str, now: Optional[float] = None) -> Tuple[bool, float]:
        """Check if an action is allowed under the 1-action-per-10-minute rule.

        Returns (is_allowed, seconds_since_last_action_or_zero).
        """
        current_time = time.time() if now is None else float(now)
        history = self._incident_history.get(incident_id, [])
        if not history:
            return True, 0.0

        last_action_time = history[-1]
        elapsed = current_time - last_action_time
        if elapsed < self.cooldown_seconds:
            return False, elapsed
        return True, elapsed

    def record_action(self, incident_id: str, timestamp: Optional[float] = None) -> None:
        """Record that a remediation action was executed for an incident."""
        t = time.time() if timestamp is None else float(timestamp)
        if incident_id not in self._incident_history:
            self._incident_history[incident_id] = []
        self._incident_history[incident_id].append(t)

    # -------------------------------------------------------------------------
    # Tier Classification & Validation
    # -------------------------------------------------------------------------

    def classify_tier(
        self,
        action_type: str,
        affected_paths: Optional[Iterable[str]] = None,
        diff: Optional[str] = None,
        explicit_tier: Optional[Union[str, RiskTier]] = None,
    ) -> RiskTier:
        """Classify the risk tier of an action according to Architecture Section 6."""
        # 1. If explicitly T3, always keep T3
        if explicit_tier:
            tier_str = explicit_tier.value if isinstance(explicit_tier, RiskTier) else str(explicit_tier)
            if tier_str.upper() == "T3":
                return RiskTier.T3

        action_type_lower = (action_type or "").lower().strip()

        # 2. Check for inherently T3 action types
        if action_type_lower in ("migration", "data", "infra", "infrastructure", "delete_infra", "secrets"):
            return RiskTier.T3

        # 3. Check paths from diff or affected_paths for T3 patterns
        paths = list(affected_paths or [])
        if diff:
            paths.extend(extract_paths_from_diff(diff))

        for p in paths:
            norm_p = p.replace("\\", "/")
            for pattern in T3_PATH_PATTERNS:
                if re.search(pattern, norm_p, re.IGNORECASE):
                    return RiskTier.T3

        # 4. If explicit tier specified (T0, T1, T2)
        if explicit_tier:
            tier_str = explicit_tier.value if isinstance(explicit_tier, RiskTier) else str(explicit_tier)
            try:
                return RiskTier(tier_str.upper())
            except ValueError:
                pass

        # 5. Classify by action type
        if action_type_lower in ("read", "query", "logs", "metrics", "history", "git_log", "git_diff", "read_file"):
            return RiskTier.T0

        if action_type_lower in ("rollback", "revert", "config", "revert_config"):
            return RiskTier.T1

        if action_type_lower in ("patch", "code_patch", "fix", "deploy"):
            return RiskTier.T2

        # Default fallback: safe code tier
        return RiskTier.T2

    def validate_paths_and_service(
        self,
        target_service: Optional[str],
        paths: Iterable[str],
        tier: RiskTier = RiskTier.T2,
    ) -> List[str]:
        """Validate paths against allowlist and forbidden patterns, and service against allowlist."""
        violations: list[str] = []

        if target_service and target_service not in self.allowed_services:
            violations.append(
                f"Service '{target_service}' is not in allowed services list {sorted(self.allowed_services)}"
            )

        for p in paths:
            norm_p = p.replace("\\", "/")
            pure = PurePosixPath(norm_p)

            # Check absolute or traversal
            if pure.is_absolute() or ".." in pure.parts:
                violations.append(f"Forbidden path traversal or absolute path: '{p}'")
                continue

            # Check forbidden patterns (e.g. /etc/, .ssh, secret files)
            for pattern in FORBIDDEN_PATH_PATTERNS:
                if re.search(pattern, norm_p, re.IGNORECASE):
                    violations.append(f"Path '{p}' matches forbidden security pattern '{pattern}'")
                    break

            # If it's a T3 action or path matches T3 pattern, it is handled via T3 human approval policy
            is_t3_path = any(re.search(pat, norm_p, re.IGNORECASE) for pat in T3_PATH_PATTERNS)
            if is_t3_path or tier == RiskTier.T3:
                continue

            # Check allowlist prefix for standard T1/T2 changes
            if self.allowed_path_prefixes and not any(norm_p.startswith(prefix) for prefix in self.allowed_path_prefixes):
                violations.append(
                    f"Path '{p}' is outside allowed path prefixes {self.allowed_path_prefixes}"
                )

        return violations

    # -------------------------------------------------------------------------
    # Evaluation Logic
    # -------------------------------------------------------------------------

    def evaluate(
        self,
        request: ActionRequest,
        now: Optional[float] = None,
    ) -> PolicyEvaluation:
        """Evaluate an ActionRequest against the safety gate policy."""
        # 1. Extract paths
        paths: list[str] = list(request.affected_paths or [])
        if request.diff:
            paths.extend(extract_paths_from_diff(request.diff))
        paths = list(dict.fromkeys(paths))

        # 2. Determine Risk Tier
        tier = self.classify_tier(
            action_type=request.action_type,
            affected_paths=paths,
            diff=request.diff,
            explicit_tier=request.risk_tier,
        )

        # 3. Check Global Kill Switch
        if self.is_kill_switch_active():
            reason = self._kill_switch_reason or "Global kill switch is active: all remediation actions halted"
            return PolicyEvaluation(
                decision=GateDecision.REJECTED,
                risk_tier=tier,
                reason=reason,
                allowed=False,
                requires_approval=False,
                violations=["KILL_SWITCH_ACTIVE"],
                incident_id=request.incident_id,
            )

        # 4. Check Path & Service Allowlist (for non-T0 actions)
        if tier != RiskTier.T0:
            path_violations = self.validate_paths_and_service(request.target_service, paths, tier=tier)
            if path_violations:
                return PolicyEvaluation(
                    decision=GateDecision.REJECTED,
                    risk_tier=tier,
                    reason=f"Safety policy violation: {'; '.join(path_violations)}",
                    allowed=False,
                    requires_approval=False,
                    violations=path_violations,
                    incident_id=request.incident_id,
                )

        # 5. Check Rate Limiting / Cooldown (for mutating actions: T1, T2, T3)
        if tier != RiskTier.T0:
            is_allowed_rate, elapsed = self.check_rate_limit(request.incident_id, now=now)
            if not is_allowed_rate:
                reason = (
                    f"Rate limit exceeded: one action per incident per 10 minutes (600s). "
                    f"Last action was {elapsed:.1f}s ago."
                )
                return PolicyEvaluation(
                    decision=GateDecision.REJECTED,
                    risk_tier=tier,
                    reason=reason,
                    allowed=False,
                    requires_approval=False,
                    violations=["RATE_LIMIT_COOLDOWN_ACTIVE"],
                    incident_id=request.incident_id,
                )

        # 6. Evaluate Tier-Specific Policy (Section 6)
        # T0: Read logs, metrics, code, history -> Always automatic
        if tier == RiskTier.T0:
            return PolicyEvaluation(
                decision=GateDecision.AUTOMATIC,
                risk_tier=RiskTier.T0,
                reason="T0 read operations are always automatic",
                allowed=True,
                requires_approval=False,
                incident_id=request.incident_id,
            )

        # T1: Roll back deploy / revert config -> Automatic if confidence >= 0.80
        if tier == RiskTier.T1:
            if request.confidence >= self.t1_confidence_threshold:
                return PolicyEvaluation(
                    decision=GateDecision.AUTOMATIC,
                    risk_tier=RiskTier.T1,
                    reason=(
                        f"T1 {request.action_type} approved automatically: "
                        f"confidence ({request.confidence:.2f}) >= threshold ({self.t1_confidence_threshold:.2f})"
                    ),
                    allowed=True,
                    requires_approval=False,
                    incident_id=request.incident_id,
                )
            else:
                return PolicyEvaluation(
                    decision=GateDecision.HUMAN_APPROVAL_REQUIRED,
                    risk_tier=RiskTier.T1,
                    reason=(
                        f"T1 {request.action_type} requires human approval: "
                        f"confidence ({request.confidence:.2f}) < threshold ({self.t1_confidence_threshold:.2f})"
                    ),
                    allowed=False,
                    requires_approval=True,
                    incident_id=request.incident_id,
                )

        # T2: Code patch -> PR plus sandbox tests plus canary; auto-merge only in demo env at confidence >= 0.85
        if tier == RiskTier.T2:
            is_demo = request.environment.lower() == "demo" and self.demo_mode
            if not is_demo:
                return PolicyEvaluation(
                    decision=GateDecision.HUMAN_APPROVAL_REQUIRED,
                    risk_tier=RiskTier.T2,
                    reason=(
                        f"T2 code patch requires human approval in non-demo environment '{request.environment}' "
                        f"(auto-execution permitted only in demo environment)"
                    ),
                    allowed=False,
                    requires_approval=True,
                    incident_id=request.incident_id,
                )

            if request.confidence >= self.t2_confidence_threshold:
                return PolicyEvaluation(
                    decision=GateDecision.AUTOMATIC,
                    risk_tier=RiskTier.T2,
                    reason=(
                        f"T2 code patch approved automatically in demo environment: "
                        f"confidence ({request.confidence:.2f}) >= threshold ({self.t2_confidence_threshold:.2f})"
                    ),
                    allowed=True,
                    requires_approval=False,
                    incident_id=request.incident_id,
                )
            else:
                return PolicyEvaluation(
                    decision=GateDecision.HUMAN_APPROVAL_REQUIRED,
                    risk_tier=RiskTier.T2,
                    reason=(
                        f"T2 code patch requires human approval: "
                        f"confidence ({request.confidence:.2f}) < threshold ({self.t2_confidence_threshold:.2f})"
                    ),
                    allowed=False,
                    requires_approval=True,
                    incident_id=request.incident_id,
                )

        # T3: Data, migrations, secrets, deleting infra -> Always human approval; NEVER automatic!
        return PolicyEvaluation(
            decision=GateDecision.HUMAN_APPROVAL_REQUIRED,
            risk_tier=RiskTier.T3,
            reason=(
                f"T3 high-risk action ({request.action_type}) strictly requires human approval. "
                "Autonomous execution is never permitted for T3."
            ),
            allowed=False,
            requires_approval=True,
            incident_id=request.incident_id,
        )

    # -------------------------------------------------------------------------
    # FixProposal Helper Integration
    # -------------------------------------------------------------------------

    def evaluate_proposal(
        self,
        proposal: FixProposal,
        confidence: float = 1.0,
        incident_id: str = "inc_default",
        environment: str = "demo",
        now: Optional[float] = None,
    ) -> PolicyEvaluation:
        """Evaluate a FixProposal model against safety policy."""
        request = ActionRequest(
            incident_id=incident_id,
            action_type=proposal.type,
            target_service=proposal.target_service or "orders",
            risk_tier=RiskTier(proposal.risk_tier),
            confidence=confidence,
            diff=proposal.diff,
            environment=environment,
            rationale=proposal.rationale,
        )
        return self.evaluate(request, now=now)
