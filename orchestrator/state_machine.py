"""Orchestrator State Machine for Incident Remediation (Day 6 Tasks B1 & B2).

Mandated States:
  - Detected: Incident received from Detector / Telemetry.
  - Investigating: Autonomous Root Cause Analysis in progress.
  - Proposed: Fix proposal generated with diff, rationale, risk tier.
  - Gated: Safety Gate evaluation against policy and risk tier.
  - Verifying: Verification pipeline (Sandbox -> Canary -> Promotion).
  - Resolved: System health verified and recovered (terminal).
  - Escalated: Human intervention required or unrecoverable error (terminal).
  - RolledBack: Post-promotion metrics degraded or T1 rollback executed (terminal).

Owner: Person B (Brain & Trust)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("nightshift.orchestrator.state_machine")


class IncidentState(str, Enum):
    """Incident remediation lifecycle states (Day 6 Task B1)."""
    DETECTED = "Detected"
    INVESTIGATING = "Investigating"
    PROPOSED = "Proposed"
    GATED = "Gated"
    VERIFYING = "Verifying"
    RESOLVED = "Resolved"
    ESCALATED = "Escalated"
    ROLLEDBACK = "RolledBack"


@dataclass
class StateTransition:
    """Record of a state machine transition."""
    from_state: IncidentState
    to_state: IncidentState
    timestamp: float
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class InvalidStateTransitionError(RuntimeError):
    """Raised when an illegal state transition is attempted."""
    pass


class StateMachine:
    """State machine enforcing strict transitions and dispatching state change events."""

    # Allowed transitions matrix
    VALID_TRANSITIONS: Dict[IncidentState, Set[IncidentState]] = {
        IncidentState.DETECTED: {
            IncidentState.INVESTIGATING,
            IncidentState.ESCALATED,
        },
        IncidentState.INVESTIGATING: {
            IncidentState.PROPOSED,
            IncidentState.ESCALATED,
        },
        IncidentState.PROPOSED: {
            IncidentState.GATED,
            IncidentState.ESCALATED,
        },
        IncidentState.GATED: {
            IncidentState.VERIFYING,
            IncidentState.ESCALATED,
            IncidentState.ROLLEDBACK,
        },
        IncidentState.VERIFYING: {
            IncidentState.RESOLVED,
            IncidentState.ROLLEDBACK,
            IncidentState.ESCALATED,
        },
        # Terminal states have no forward transitions
        IncidentState.RESOLVED: set(),
        IncidentState.ESCALATED: set(),
        IncidentState.ROLLEDBACK: set(),
    }

    def __init__(
        self,
        incident_id: str,
        initial_state: IncidentState = IncidentState.DETECTED,
        on_transition: Optional[Callable[[StateTransition], None]] = None,
    ) -> None:
        self.incident_id = incident_id
        self.current_state = initial_state
        self.on_transition = on_transition

        self.history: List[StateTransition] = []
        self._emitted_signatures: Set[str] = set()

    @property
    def is_terminal(self) -> bool:
        """True if the state machine is in a terminal state (Resolved, Escalated, RolledBack)."""
        return self.current_state in (
            IncidentState.RESOLVED,
            IncidentState.ESCALATED,
            IncidentState.ROLLEDBACK,
        )

    def can_transition_to(self, new_state: IncidentState) -> bool:
        """Check whether transitioning to new_state is allowed from the current state."""
        return new_state in self.VALID_TRANSITIONS.get(self.current_state, set())

    def transition(
        self,
        new_state: IncidentState,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StateTransition:
        """Execute a state transition, enforce valid transitions, and invoke listener."""
        if not self.can_transition_to(new_state):
            raise InvalidStateTransitionError(
                f"Cannot transition incident '{self.incident_id}' from {self.current_state.value} to {new_state.value}"
            )

        old_state = self.current_state
        now = time.time()
        record = StateTransition(
            from_state=old_state,
            to_state=new_state,
            timestamp=now,
            reason=reason,
            metadata=metadata or {},
        )

        self.current_state = new_state
        self.history.append(record)

        logger.info(
            "Incident %s state transition: %s -> %s (reason: %s)",
            self.incident_id,
            old_state.value,
            new_state.value,
            reason,
        )

        # Dispatch transition notification (Task B2)
        # Deduplication key ensures no duplicate notifications are sent
        sig = f"{self.incident_id}:{old_state.value}:{new_state.value}:{len(self.history)}"
        if sig not in self._emitted_signatures:
            self._emitted_signatures.add(sig)
            if self.on_transition is not None:
                try:
                    self.on_transition(record)
                except Exception as exc:
                    logger.warning("Error in on_transition callback: %s", exc)

        return record
