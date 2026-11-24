"""Unit and integration tests for HumanApprovalManager (Day 5 Task B2).

Owner: Person B
Testing criteria:
1. Approve executes once.
2. Reject does nothing (execution count is 0).
3. Timeout leads to escalation.
4. Double click is idempotent (executes only once).
5. Slack message contains interactive Approve and Reject action buttons.
6. CLI fallback prompt properly approves or rejects based on operator input.
"""

import time
import unittest
from unittest.mock import MagicMock

from contracts.models import FixProposal
from reporter.slack import SlackReporter
from safety.approval import (
    ApprovalDecision,
    ApprovalSession,
    ApprovalStatus,
    HumanApprovalManager,
)


def _make_dummy_proposal(risk_tier: str = "T2") -> FixProposal:
    return FixProposal(
        type="patch",
        diff="diff --git a/services/orders/app.py b/services/orders/app.py\n--- a/services/orders/app.py\n+++ b/services/orders/app.py\n@@ -1 +1 @@",
        risk_tier=risk_tier,
        rationale="Fix null pointer exception in VIP user handling",
        expected_metric_effect="Error rate drops to 0%",
        target_service="orders",
    )


class TestHumanApprovalManager(unittest.TestCase):
    """Test suite verifying human approval path criteria (Day 5 Task B2)."""

    def setUp(self):
        self.slack_reporter = SlackReporter(mock=True)
        self.manager = HumanApprovalManager(
            slack_reporter=self.slack_reporter,
            default_timeout_seconds=300.0,
        )

    def test_approve_executes_once(self):
        """Criterion 1: Approving a fix executes the action callback exactly once."""
        mock_executor = MagicMock(return_value={"deployed": True, "version": "v1.0.1"})
        proposal = _make_dummy_proposal()

        session = self.manager.create_request(
            incident_id="inc-approve-01",
            proposal=proposal,
            execute_fn=mock_executor,
        )

        self.assertEqual(session.status, ApprovalStatus.PENDING)
        self.assertEqual(session.execution_count, 0)
        mock_executor.assert_not_called()

        # Approve the request
        res = self.manager.handle_response(
            request_id=session.request_id,
            decision=ApprovalDecision.APPROVE,
            user="alice_sre",
        )

        self.assertEqual(res.status, ApprovalStatus.APPROVED)
        self.assertEqual(res.resolved_by, "alice_sre")
        self.assertIsNotNone(res.resolved_at)
        self.assertEqual(res.execution_count, 1)
        self.assertEqual(res.execution_result, {"deployed": True, "version": "v1.0.1"})
        mock_executor.assert_called_once_with(proposal)

    def test_reject_does_nothing(self):
        """Criterion 2: Rejecting a fix does nothing (executor is never called, execution_count == 0)."""
        mock_executor = MagicMock()
        proposal = _make_dummy_proposal()

        session = self.manager.create_request(
            incident_id="inc-reject-01",
            proposal=proposal,
            execute_fn=mock_executor,
        )

        # Reject the request
        res = self.manager.handle_response(
            request_id=session.request_id,
            decision=ApprovalDecision.REJECT,
            user="bob_lead",
        )

        self.assertEqual(res.status, ApprovalStatus.REJECTED)
        self.assertEqual(res.resolved_by, "bob_lead")
        self.assertEqual(res.execution_count, 0)
        self.assertIsNone(res.execution_result)
        mock_executor.assert_not_called()

    def test_timeout_leads_to_escalation(self):
        """Criterion 3: Timeout leads to escalation and remediation is not executed."""
        mock_executor = MagicMock()
        escalation_hook = MagicMock()
        self.manager.escalation_callback = escalation_hook

        proposal = _make_dummy_proposal(risk_tier="T3")
        t0 = 50000.0

        session = self.manager.create_request(
            incident_id="inc-timeout-01",
            proposal=proposal,
            timeout_seconds=60.0,
            execute_fn=mock_executor,
        )
        session.created_at = t0

        # Check timeouts before expiration (t0 + 30s) -> still pending
        escalated_early = self.manager.check_timeouts(now=t0 + 30.0)
        self.assertEqual(len(escalated_early), 0)
        self.assertEqual(session.status, ApprovalStatus.PENDING)

        # Check timeouts after expiration (t0 + 61s) -> ESCALATED
        escalated_late = self.manager.check_timeouts(now=t0 + 61.0)
        self.assertEqual(len(escalated_late), 1)
        self.assertEqual(session.status, ApprovalStatus.ESCALATED)
        self.assertEqual(session.execution_count, 0)
        mock_executor.assert_not_called()
        escalation_hook.assert_called_once_with(session)

        # Slack escalation message was sent
        slack_texts = [msg["payload"]["text"] for msg in self.slack_reporter.sent_messages]
        self.assertTrue(any("ESCALATED" in txt for txt in slack_texts))

        # Late approval attempt after escalation is ignored
        late_res = self.manager.handle_response(session.request_id, ApprovalDecision.APPROVE)
        self.assertEqual(late_res.status, ApprovalStatus.ESCALATED)
        self.assertEqual(late_res.execution_count, 0)
        mock_executor.assert_not_called()

    def test_double_click_is_idempotent(self):
        """Criterion 4: Double click on approve is idempotent; callback executes exactly once."""
        mock_executor = MagicMock(return_value="remediation_applied_successfully")
        proposal = _make_dummy_proposal()

        session = self.manager.create_request(
            incident_id="inc-doubleclick-01",
            proposal=proposal,
            execute_fn=mock_executor,
        )

        # First click -> Executes
        res1 = self.manager.handle_response(session.request_id, ApprovalDecision.APPROVE, user="alice")
        self.assertEqual(res1.status, ApprovalStatus.APPROVED)
        self.assertEqual(res1.execution_count, 1)
        mock_executor.assert_called_once()

        # Second click -> Idempotent! Does not re-execute
        res2 = self.manager.handle_response(session.request_id, ApprovalDecision.APPROVE, user="alice")
        self.assertEqual(res2.status, ApprovalStatus.APPROVED)
        self.assertEqual(res2.execution_count, 1)
        mock_executor.assert_called_once()

        # Third click by another user -> Still idempotent
        res3 = self.manager.handle_response(session.request_id, ApprovalDecision.APPROVE, user="bob")
        self.assertEqual(res3.status, ApprovalStatus.APPROVED)
        self.assertEqual(res3.execution_count, 1)
        mock_executor.assert_called_once()

    def test_slack_message_contains_interactive_buttons(self):
        """Slack approval message includes Block Kit action buttons with approve and reject."""
        proposal = _make_dummy_proposal()
        session = self.manager.create_request(
            incident_id="inc-slack-buttons-01",
            proposal=proposal,
        )

        self.assertGreaterEqual(len(self.slack_reporter.sent_messages), 1)
        last_msg = self.slack_reporter.sent_messages[-1]
        blocks = last_msg["payload"].get("blocks", [])

        # Find actions block
        actions_blocks = [b for b in blocks if b.get("type") == "actions"]
        self.assertEqual(len(actions_blocks), 1)

        elements = actions_blocks[0].get("elements", [])
        self.assertEqual(len(elements), 2)

        action_ids = [el.get("action_id") for el in elements]
        self.assertIn("approve_fix", action_ids)
        self.assertIn("reject_fix", action_ids)

        # Verify button values reference the request ID
        values = [el.get("value") for el in elements]
        self.assertEqual(values, [session.request_id, session.request_id])

    def test_cli_fallback_approval(self):
        """CLI fallback handles operator confirmation."""
        mock_executor = MagicMock(return_value="cli_applied")
        proposal = _make_dummy_proposal()
        session = self.manager.create_request(
            incident_id="inc-cli-01",
            proposal=proposal,
            execute_fn=mock_executor,
        )

        # Simulate operator entering 'yes'
        res = self.manager.prompt_cli(session, responder_fn=lambda: "yes")
        self.assertEqual(res.status, ApprovalStatus.APPROVED)
        self.assertEqual(res.resolved_by, "cli_operator")
        self.assertEqual(res.execution_count, 1)
        mock_executor.assert_called_once()

    def test_cli_fallback_rejection(self):
        """CLI fallback handles operator rejection."""
        mock_executor = MagicMock()
        proposal = _make_dummy_proposal()
        session = self.manager.create_request(
            incident_id="inc-cli-02",
            proposal=proposal,
            execute_fn=mock_executor,
        )

        # Simulate operator entering 'no'
        res = self.manager.prompt_cli(session, responder_fn=lambda: "no")
        self.assertEqual(res.status, ApprovalStatus.REJECTED)
        self.assertEqual(res.resolved_by, "cli_operator")
        self.assertEqual(res.execution_count, 0)
        mock_executor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
