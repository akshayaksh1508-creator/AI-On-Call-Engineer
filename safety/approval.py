"""Human approval path and interactive sign-off manager for remediations.

Owner: Person B
Architecture Section 6 & Day 5 Task B2:
- Slack message with interactive approve and reject buttons
- CLI fallback prompt mechanism
- Timeout leads to automatic escalation
- Approve executes callback exactly once
- Reject does nothing (no execution)
- Double click is idempotent (executes only once)
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

from contracts.models import FixProposal
from reporter.slack import SlackReporter

logger = logging.getLogger("safety.approval")


class ApprovalStatus(str, Enum):
    """Lifecycle statuses for a human approval request."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TIMED_OUT = "TIMED_OUT"
    ESCALATED = "ESCALATED"


class ApprovalDecision(str, Enum):
    """User decision for an approval request."""
    APPROVE = "APPROVE"
    REJECT = "REJECT"


@dataclass
class ApprovalSession:
    """State tracking for an interactive human approval request."""
    request_id: str
    incident_id: str
    proposal: FixProposal
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: float = field(default_factory=time.time)
    timeout_seconds: float = 300.0
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None
    execution_count: int = 0
    execution_result: Optional[Any] = None
    execute_fn: Optional[Callable[[FixProposal], Any]] = None
    audit_events: List[Dict[str, Any]] = field(default_factory=list)

    def log_event(self, action: str, details: str, actor: str = "system") -> None:
        """Append an audit entry to the approval session."""
        self.audit_events.append({
            "timestamp": time.time(),
            "actor": actor,
            "action": action,
            "details": details,
            "status": self.status.value,
        })


class HumanApprovalManager:
    """Manages the lifecycle of remediation approval requests via Slack and CLI fallback."""

    def __init__(
        self,
        slack_reporter: Optional[SlackReporter] = None,
        default_timeout_seconds: float = 300.0,
        escalation_callback: Optional[Callable[[ApprovalSession], Any]] = None,
    ) -> None:
        self.slack_reporter = slack_reporter or SlackReporter(mock=True)
        self.default_timeout_seconds = float(default_timeout_seconds)
        self.escalation_callback = escalation_callback
        self._sessions: Dict[str, ApprovalSession] = {}

    def get_session(self, request_id: str) -> Optional[ApprovalSession]:
        """Retrieve an approval session by request ID."""
        return self._sessions.get(request_id)

    def create_request(
        self,
        incident_id: str,
        proposal: FixProposal,
        timeout_seconds: Optional[float] = None,
        execute_fn: Optional[Callable[[FixProposal], Any]] = None,
        request_id: Optional[str] = None,
    ) -> ApprovalSession:
        """Create and dispatch an interactive human sign-off request."""
        req_id = request_id or f"apr_{uuid.uuid4().hex[:12]}"
        timeout = float(timeout_seconds if timeout_seconds is not None else self.default_timeout_seconds)

        session = ApprovalSession(
            request_id=req_id,
            incident_id=incident_id,
            proposal=proposal,
            status=ApprovalStatus.PENDING,
            timeout_seconds=timeout,
            execute_fn=execute_fn,
        )
        session.log_event("CREATED", f"Created approval request with {timeout:.0f}s timeout")
        self._sessions[req_id] = session

        # Dispatch Slack interactive approval request
        if self.slack_reporter:
            try:
                self.slack_reporter.send_approval_request(
                    incident_id=incident_id,
                    proposal=proposal,
                    request_id=req_id,
                )
                session.log_event("SLACK_DISPATCHED", f"Dispatched approval buttons to Slack for {req_id}")
            except Exception as exc:
                logger.error("Failed to dispatch Slack approval request: %s", exc)
                session.log_event("SLACK_ERROR", str(exc))

        return session

    def handle_response(
        self,
        request_id: str,
        decision: Union[ApprovalDecision, str],
        user: str = "operator",
    ) -> ApprovalSession:
        """Process an approve or reject decision.

        Idempotency guarantee: Double click / repeat approval executes callback exactly ONCE.
        Reject guarantee: Reject does nothing (execution_count remains 0).
        """
        session = self._sessions.get(request_id)
        if not session:
            raise KeyError(f"Approval request '{request_id}' not found")

        # Normalize decision
        decision_str = decision.value if isinstance(decision, ApprovalDecision) else str(decision).upper()

        # Check existing state for idempotency
        if session.status == ApprovalStatus.APPROVED:
            logger.info("Ignoring duplicate approval click for already APPROVED request %s by %s", request_id, user)
            session.log_event("DOUBLE_CLICK_IGNORED", f"Ignored duplicate approval click by {user}", actor=user)
            return session

        if session.status in (ApprovalStatus.REJECTED, ApprovalStatus.TIMED_OUT, ApprovalStatus.ESCALATED):
            logger.warning(
                "Cannot apply decision %s to request %s currently in %s state",
                decision_str,
                request_id,
                session.status.value,
            )
            session.log_event("DECISION_IGNORED", f"Ignored decision {decision_str} in state {session.status.value}", actor=user)
            return session

        now = time.time()

        if decision_str == ApprovalDecision.APPROVE.value:
            session.status = ApprovalStatus.APPROVED
            session.resolved_at = now
            session.resolved_by = user
            session.log_event("APPROVED", f"Approved by {user}", actor=user)

            # Execute callback exactly once
            if session.execute_fn is not None:
                try:
                    session.execution_result = session.execute_fn(session.proposal)
                    session.execution_count += 1
                    session.log_event(
                        "EXECUTED",
                        f"Remediation executed successfully (count={session.execution_count})",
                        actor="system",
                    )
                except Exception as exc:
                    session.execution_count += 1
                    session.execution_result = {"error": str(exc)}
                    session.log_event("EXECUTION_ERROR", str(exc), actor="system")
                    logger.error("Error executing approved fix for %s: %s", request_id, exc)
            else:
                session.execution_count += 1
                session.log_event("APPROVED_NO_CALLBACK", "Approved without execute callback")

            return session

        elif decision_str == ApprovalDecision.REJECT.value:
            session.status = ApprovalStatus.REJECTED
            session.resolved_at = now
            session.resolved_by = user
            session.log_event("REJECTED", f"Rejected by {user}; no remediation executed", actor=user)
            # Guarantee: Reject does nothing, execution_count remains 0
            return session

        else:
            raise ValueError(f"Unknown approval decision: '{decision}' (expected APPROVE or REJECT)")

    def check_timeouts(self, now: Optional[float] = None) -> List[ApprovalSession]:
        """Check all pending approval requests and escalate any that exceeded their timeout window."""
        current_time = time.time() if now is None else float(now)
        escalated_sessions: List[ApprovalSession] = []

        for session in list(self._sessions.values()):
            if session.status != ApprovalStatus.PENDING:
                continue

            elapsed = current_time - session.created_at
            if elapsed >= session.timeout_seconds:
                session.status = ApprovalStatus.ESCALATED
                session.resolved_at = current_time
                session.resolved_by = "timeout_daemon"
                session.log_event(
                    "TIMED_OUT",
                    f"Approval request timed out after {elapsed:.1f}s (limit: {session.timeout_seconds:.1f}s)",
                )
                session.log_event("ESCALATED", "Incident escalated to on-call engineer due to approval timeout")

                # Dispatch escalation notice to Slack
                if self.slack_reporter:
                    reason = (
                        f"Approval request timed out after {elapsed:.0f}s "
                        f"(threshold: {session.timeout_seconds:.0f}s). Escalating to human on-call engineer."
                    )
                    try:
                        self.slack_reporter.send_escalation_alert(
                            incident_id=session.incident_id,
                            reason=reason,
                            proposal=session.proposal,
                        )
                    except Exception as exc:
                        logger.error("Failed to send Slack escalation alert: %s", exc)

                # Invoke escalation callback if registered
                if self.escalation_callback:
                    try:
                        self.escalation_callback(session)
                    except Exception as exc:
                        logger.error("Escalation callback raised error: %s", exc)

                escalated_sessions.append(session)

        return escalated_sessions

    def prompt_cli(
        self,
        session: ApprovalSession,
        responder_fn: Optional[Callable[[], str]] = None,
    ) -> ApprovalSession:
        """CLI fallback interaction: prompt the terminal operator for approval decision."""
        proposal = session.proposal
        print("=" * 60)
        print(f"[HUMAN APPROVAL REQUIRED] Incident: {session.incident_id}")
        print(f"Risk Tier: {proposal.risk_tier} | Remediation Type: {proposal.type} | Service: {proposal.target_service}")
        print(f"Rationale: {proposal.rationale}")
        print(f"Expected Metric Effect: {proposal.expected_metric_effect}")
        if proposal.diff:
            diff_lines = proposal.diff.strip().splitlines()
            preview = "\n".join(diff_lines[:6])
            print(f"Diff Preview:\n{preview}")
        print("=" * 60)

        # Get response via responder_fn or fallback to built-in input
        if responder_fn is not None:
            raw_input = responder_fn()
        else:
            try:
                raw_input = input("Approve remediation? [y/N]: ")
            except (EOFError, KeyboardInterrupt):
                raw_input = "n"

        choice = (raw_input or "").strip().lower()
        if choice in ("y", "yes", "approve", "a"):
            return self.handle_response(session.request_id, ApprovalDecision.APPROVE, user="cli_operator")
        else:
            return self.handle_response(session.request_id, ApprovalDecision.REJECT, user="cli_operator")
