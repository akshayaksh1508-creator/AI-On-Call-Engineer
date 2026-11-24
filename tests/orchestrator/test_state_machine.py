"""Unit tests for Orchestrator State Machine and Reporter (Day 6 Tasks B1 & B2).

Verifies:
1. Every state machine transition:
   - Happy path: Detected -> Investigating -> Proposed -> Gated -> Verifying -> Resolved
   - Rollback path: Detected -> Investigating -> Proposed -> Gated -> Verifying -> RolledBack
   - Escalation paths from each active state
   - Illegal transitions raise InvalidStateTransitionError
   - Terminal states cannot transition
2. Orchestrator failure handling:
   - LLM timeout during investigation
   - Tool crash during investigation
   - Safety gate rejection
   - Verifier error / crash
   - Verifier canary rollback
3. Reporter stub (Task B2 criterion):
   - Slack state change messages arrive in strict sequential order
   - Zero duplicate messages across 3 consecutive runs
"""

from __future__ import annotations

import time
import unittest
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

from bench.stage_timer import StageTimer
from contracts.models import FixProposal, Hypothesis, Incident, VerificationResult
from deployer.executor import ActionExecutor, ExecutionResult
from orchestrator.engine import OrchestratorEngine, OrchestratorRunResult
from orchestrator.state_machine import (
    IncidentState,
    InvalidStateTransitionError,
    StateMachine,
    StateTransition,
)
from reporter.github_pr import GitHubPRClient
from reporter.slack import SlackReporter
from safety.gate import GateDecision, PolicyEvaluation, RiskTier, SafetyGate


class TestStateMachineTransitions(unittest.TestCase):
    """Test transitions and enforcement of the IncidentState state machine."""

    def test_happy_path_transitions(self):
        """Verify full lifecycle: Detected -> Investigating -> Proposed -> Gated -> Verifying -> Resolved."""
        transitions: List[StateTransition] = []
        sm = StateMachine(
            incident_id="inc_001",
            initial_state=IncidentState.DETECTED,
            on_transition=lambda t: transitions.append(t),
        )

        self.assertEqual(sm.current_state, IncidentState.DETECTED)
        self.assertFalse(sm.is_terminal)

        # 1. Detected -> Investigating
        t1 = sm.transition(IncidentState.INVESTIGATING, reason="Investigating alert")
        self.assertEqual(sm.current_state, IncidentState.INVESTIGATING)
        self.assertEqual(t1.from_state, IncidentState.DETECTED)
        self.assertEqual(t1.to_state, IncidentState.INVESTIGATING)

        # 2. Investigating -> Proposed
        t2 = sm.transition(IncidentState.PROPOSED, reason="Patch proposed")
        self.assertEqual(sm.current_state, IncidentState.PROPOSED)

        # 3. Proposed -> Gated
        t3 = sm.transition(IncidentState.GATED, reason="Safety check passed")
        self.assertEqual(sm.current_state, IncidentState.GATED)

        # 4. Gated -> Verifying
        t4 = sm.transition(IncidentState.VERIFYING, reason="Canary verification started")
        self.assertEqual(sm.current_state, IncidentState.VERIFYING)

        # 5. Verifying -> Resolved
        t5 = sm.transition(IncidentState.RESOLVED, reason="Verification passed")
        self.assertEqual(sm.current_state, IncidentState.RESOLVED)
        self.assertTrue(sm.is_terminal)

        # Verify history
        self.assertEqual(len(sm.history), 5)
        self.assertEqual(len(transitions), 5)
        self.assertEqual(
            [t.to_state for t in sm.history],
            [
                IncidentState.INVESTIGATING,
                IncidentState.PROPOSED,
                IncidentState.GATED,
                IncidentState.VERIFYING,
                IncidentState.RESOLVED,
            ],
        )

    def test_rollback_transition(self):
        """Verify rollback path: Verifying -> RolledBack."""
        sm = StateMachine(incident_id="inc_002")
        sm.transition(IncidentState.INVESTIGATING)
        sm.transition(IncidentState.PROPOSED)
        sm.transition(IncidentState.GATED)
        sm.transition(IncidentState.VERIFYING)
        sm.transition(IncidentState.ROLLEDBACK, reason="Canary threshold violated")

        self.assertEqual(sm.current_state, IncidentState.ROLLEDBACK)
        self.assertTrue(sm.is_terminal)

    def test_escalation_from_all_active_states(self):
        """Verify Escalated transition is reachable from any non-terminal state."""
        active_states = [
            IncidentState.DETECTED,
            IncidentState.INVESTIGATING,
            IncidentState.PROPOSED,
            IncidentState.GATED,
            IncidentState.VERIFYING,
        ]

        for state in active_states:
            with self.subTest(from_state=state):
                sm = StateMachine(incident_id=f"inc_esc_{state.value}", initial_state=state)
                t = sm.transition(IncidentState.ESCALATED, reason=f"Escalation from {state.value}")
                self.assertEqual(sm.current_state, IncidentState.ESCALATED)
                self.assertEqual(t.to_state, IncidentState.ESCALATED)
                self.assertTrue(sm.is_terminal)

    def test_invalid_transition_raises_error(self):
        """Verify invalid or skipped transitions raise InvalidStateTransitionError."""
        sm = StateMachine(incident_id="inc_invalid", initial_state=IncidentState.DETECTED)

        # Cannot skip from Detected directly to Resolved
        with self.assertRaises(InvalidStateTransitionError):
            sm.transition(IncidentState.RESOLVED)

        # Cannot skip from Detected directly to Verifying
        with self.assertRaises(InvalidStateTransitionError):
            sm.transition(IncidentState.VERIFYING)

        # Advance to Investigating
        sm.transition(IncidentState.INVESTIGATING)

        # Cannot go backwards to Detected
        with self.assertRaises(InvalidStateTransitionError):
            sm.transition(IncidentState.DETECTED)

    def test_terminal_state_cannot_transition(self):
        """Verify terminal states (Resolved, RolledBack, Escalated) reject further transitions."""
        for terminal in [IncidentState.RESOLVED, IncidentState.ROLLEDBACK, IncidentState.ESCALATED]:
            with self.subTest(terminal=terminal):
                sm = StateMachine(incident_id=f"inc_{terminal.value}", initial_state=terminal)
                self.assertTrue(sm.is_terminal)
                with self.assertRaises(InvalidStateTransitionError):
                    sm.transition(IncidentState.INVESTIGATING)
                with self.assertRaises(InvalidStateTransitionError):
                    sm.transition(IncidentState.RESOLVED)


class TestOrchestratorFailureHandling(unittest.TestCase):
    """Test Orchestrator failure handling: LLM timeout, tool crash, safety gate, verifier crash."""

    def setUp(self):
        self.incident = Incident(
            id="inc_test_fail",
            service="orders",
            started_at="2026-11-24T12:00:00Z",
            symptoms=["500 Internal Server Error spike"],
            alerts=["OrderFailureSpike"],
        )

    def test_llm_timeout_transitions_to_escalated(self):
        """LLM timeout during RCA must transition state cleanly to Escalated."""
        engine = OrchestratorEngine()
        result = engine.handle_incident(self.incident, force_timeout=True)

        self.assertFalse(result.success)
        self.assertEqual(result.final_state, IncidentState.ESCALATED)
        self.assertIn("Simulated LLM call timeout", str(result.error_message))
        self.assertEqual(result.transitions[-1].to_state, IncidentState.ESCALATED)

    def test_tool_crash_transitions_to_escalated(self):
        """Tool crash (e.g. API client crash) must transition cleanly to Escalated."""
        engine = OrchestratorEngine()
        result = engine.handle_incident(self.incident, force_tool_crash=True)

        self.assertFalse(result.success)
        self.assertEqual(result.final_state, IncidentState.ESCALATED)
        self.assertIn("Simulated tool crash", str(result.error_message))
        self.assertEqual(result.transitions[-1].to_state, IncidentState.ESCALATED)

    def test_safety_gate_rejection_transitions_to_escalated(self):
        """Safety Gate policy rejection (e.g., T3 destructive action) must escalate."""
        mock_gate = MagicMock(spec=SafetyGate)
        mock_gate.evaluate.return_value = PolicyEvaluation(
            decision=GateDecision.HUMAN_APPROVAL_REQUIRED,
            risk_tier=RiskTier.T3,
            reason="T3 action requires explicit SRE approval",
            allowed=False,
            requires_approval=True,
        )

        engine = OrchestratorEngine(safety_gate=mock_gate)
        result = engine.handle_incident(self.incident)

        self.assertFalse(result.success)
        self.assertEqual(result.final_state, IncidentState.ESCALATED)
        self.assertEqual(result.transitions[-2].to_state, IncidentState.GATED)
        self.assertEqual(result.transitions[-1].to_state, IncidentState.ESCALATED)
        self.assertIn("T3 action requires explicit SRE approval", str(result.error_message))

    def test_verifier_crash_transitions_to_escalated(self):
        """Verifier runtime execution crash must transition cleanly to Escalated."""
        engine = OrchestratorEngine()
        result = engine.handle_incident(self.incident, force_verifier_crash=True)

        self.assertFalse(result.success)
        self.assertEqual(result.final_state, IncidentState.ESCALATED)
        self.assertIn("Simulated verifier engine execution failure", str(result.error_message))

    def test_verifier_post_promotion_degradation_triggers_rollback(self):
        """Post-promotion metric degradation triggers auto-rollback and transitions to RolledBack."""
        engine = OrchestratorEngine()
        result = engine.handle_incident(
            self.incident,
            fault_id="fault_001_bad_deploy",
            post_promotion_error_rate=0.35,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.final_state, IncidentState.ROLLEDBACK)
        self.assertEqual(result.transitions[-1].to_state, IncidentState.ROLLEDBACK)

    def test_verifier_canary_failure_transitions_to_escalated(self):
        """Unhealthy canary halts pipeline before promotion and transitions to Escalated."""
        engine = OrchestratorEngine()
        result = engine.handle_incident(
            self.incident,
            fault_id="fault_001_bad_deploy",
            simulated_canary_healthy=False,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.final_state, IncidentState.ESCALATED)
        self.assertEqual(result.transitions[-1].to_state, IncidentState.ESCALATED)


class TestReporterStubAndDeduplication(unittest.TestCase):
    """Test Day 6 Task B2 criterion: Slack messages arrive in order with no duplicates across 3 runs."""

    def test_slack_messages_in_order_no_duplicates_across_3_runs(self):
        """Run the orchestrator 3 consecutive times and verify strict message ordering and zero duplicates."""
        mock_slack = MagicMock(spec=SlackReporter)
        dispatched_messages: List[dict] = []

        def capture_state_change(incident_id, old_state, new_state, details=""):
            dispatched_messages.append({
                "incident_id": incident_id,
                "old_state": old_state,
                "new_state": new_state,
                "details": details,
            })

        mock_slack.send_state_change.side_effect = capture_state_change

        engine = OrchestratorEngine(reporter=mock_slack)

        for run_idx in range(1, 4):
            dispatched_messages.clear()
            incident = Incident(
                id=f"inc_run_{run_idx}",
                service="orders",
                started_at="2026-11-24T12:00:00Z",
                symptoms=["Error rate elevated"],
                alerts=["High5xxRate"],
            )

            result = engine.handle_incident(incident, fault_id="fault_001_bad_deploy")
            self.assertTrue(result.success, f"Run {run_idx} failed: {result.error_message}")
            self.assertEqual(result.final_state, IncidentState.RESOLVED)

            # Criterion 1: Expected ordered sequence of state changes
            expected_transitions = [
                ("Detected", "Investigating"),
                ("Investigating", "Proposed"),
                ("Proposed", "Gated"),
                ("Gated", "Verifying"),
                ("Verifying", "Resolved"),
            ]

            actual_transitions = [
                (msg["old_state"], msg["new_state"]) for msg in dispatched_messages
            ]

            self.assertEqual(
                actual_transitions,
                expected_transitions,
                f"Run {run_idx} messages were not in expected sequential order",
            )

            # Criterion 2: Zero duplicate messages in the sequence
            seen = set()
            for msg in dispatched_messages:
                key = (msg["incident_id"], msg["old_state"], msg["new_state"])
                self.assertNotIn(key, seen, f"Duplicate state change detected in run {run_idx}: {key}")
                seen.add(key)


if __name__ == "__main__":
    unittest.main()
