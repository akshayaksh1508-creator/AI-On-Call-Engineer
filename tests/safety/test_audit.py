"""Unit and tamper-detection tests for AuditLogger and hash chain (Day 5 Task B4).

Owner: Person B
Testing criteria:
1. Append-only audit log records who, what, why, evidence IDs, risk tier, incident ID.
2. Every executed action has an audit log entry.
3. Cryptographic hash chain links each entry to its predecessor.
4. Tamper detection: editing any character in a line is immediately detected.
5. Tamper detection: deleting a line (middle, beginning, or end) is immediately detected.
6. Tamper detection: inserting an unauthorized line breaks the chain.
7. Persistence across restarts seamlessly continues the cryptographic chain.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from contracts.models import FixProposal
from safety.approval import ApprovalDecision, HumanApprovalManager
from safety.audit import (
    GENESIS_HASH,
    AuditEntry,
    AuditLogger,
)


class TestAuditLoggerHashChain(unittest.TestCase):
    """Test suite for append-only audit logging and cryptographic tamper-detection."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.tmpdir.name) / "audit.jsonl"
        self.audit = AuditLogger(self.log_file)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_log_entry_fields_and_hash_chain(self):
        """Criterion 1: Audit entries contain who, what, why, evidence_ids and valid SHA-256 hash chaining."""
        e0 = self.audit.log_decision(
            who="agent:autonomous",
            what="rollback_deploy",
            why="Culprit commit a2b4c6e8 caused 90% error rate",
            evidence_ids=["ev_log_001", "ev_met_002"],
            incident_id="inc-20261124-001",
            target_service="orders",
            risk_tier="T1",
            status="EXECUTED",
        )

        self.assertEqual(e0.sequence, 0)
        self.assertEqual(e0.prev_hash, GENESIS_HASH)
        self.assertEqual(len(e0.entry_hash), 64)
        self.assertEqual(e0.who, "agent:autonomous")
        self.assertEqual(e0.what, "rollback_deploy")
        self.assertEqual(e0.why, "Culprit commit a2b4c6e8 caused 90% error rate")
        self.assertEqual(e0.evidence_ids, ["ev_log_001", "ev_met_002"])

        e1 = self.audit.log_decision(
            who="operator:alice",
            what="apply_patch",
            why="Manual approval of null check fix in create_order",
            evidence_ids=["ev_diff_003"],
            incident_id="inc-20261124-001",
            target_service="orders",
            risk_tier="T2",
            status="EXECUTED",
        )

        self.assertEqual(e1.sequence, 1)
        self.assertEqual(e1.prev_hash, e0.entry_hash, "Entry 1 must chain from Entry 0 hash")
        self.assertEqual(len(e1.entry_hash), 64)

        # Verify integrity of initial chain
        is_valid, msg = self.audit.verify_integrity()
        self.assertTrue(is_valid, f"Initial chain must be valid: {msg}")
        self.assertIn("2 entries intact", msg)

    def test_every_executed_action_has_an_entry_via_approval_manager(self):
        """Criterion 2: Every executed action through HumanApprovalManager generates an audit entry."""
        proposal = FixProposal(
            type="patch",
            diff="diff --git a/app.py b/app.py",
            risk_tier="T2",
            rationale="Fix null pointer exception in VIP user handling",
            expected_metric_effect="Error rate drops to 0%",
            target_service="orders",
        )

        mock_exec = MagicMock(return_value={"deployed": True})
        manager = HumanApprovalManager(
            audit_logger=self.audit,
            default_timeout_seconds=300.0,
        )

        session = manager.create_request(
            incident_id="inc-action-01",
            proposal=proposal,
            execute_fn=mock_exec,
        )

        # Before approval: 0 executed entries
        self.assertEqual(len(self.audit.read_entries()), 0)

        # Approve and execute
        manager.handle_response(session.request_id, ApprovalDecision.APPROVE, user="alice")
        mock_exec.assert_called_once()

        # Audit log must have recorded the executed action
        entries = self.audit.read_entries()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry.who, "operator:alice")
        self.assertEqual(entry.what, "execute_patch")
        self.assertEqual(entry.status, "EXECUTED")
        self.assertEqual(entry.incident_id, "inc-action-01")
        self.assertEqual(entry.why, proposal.rationale)

        # Now test rejection generates a rejection audit entry
        session2 = manager.create_request(incident_id="inc-action-02", proposal=proposal)
        manager.handle_response(session2.request_id, ApprovalDecision.REJECT, user="bob")

        entries_after = self.audit.read_entries()
        self.assertEqual(len(entries_after), 2)
        self.assertEqual(entries_after[1].status, "REJECTED")
        self.assertEqual(entries_after[1].who, "operator:bob")

        # Verify integrity of the audit chain
        is_valid, msg = self.audit.verify_integrity()
        self.assertTrue(is_valid, msg)

    def test_tamper_detection_line_edited(self):
        """Criterion 4: Modifying any character or field in an audit line is immediately detected."""
        for i in range(5):
            self.audit.log_decision(
                who=f"agent_{i}",
                what=f"action_{i}",
                why=f"Diagnostic reason {i}",
                evidence_ids=[f"ev_{i}"],
                incident_id="inc-tamper-edit",
            )

        # Initial check passes
        is_valid, _ = self.audit.verify_integrity()
        self.assertTrue(is_valid)

        # Tamper: Edit line 2 (sequence 2) in the file
        lines = self.log_file.read_text(encoding="utf-8").splitlines()
        record_2 = json.loads(lines[2])
        # Malicious edit: change reason or who
        record_2["why"] = "Tampered diagnostic rationale injected by attacker"
        lines[2] = json.dumps(record_2, sort_keys=True)
        self.log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Verify integrity detects tampering
        is_valid, msg = self.audit.verify_integrity()
        self.assertFalse(is_valid, "Editing a line must fail verification")
        self.assertIn("content was edited", msg)
        self.assertIn("seq 2", msg)

    def test_tamper_detection_line_deleted_from_middle(self):
        """Criterion 5: Deleting a line from the middle of the log breaks the hash chain."""
        for i in range(5):
            self.audit.log_decision(
                who=f"agent_{i}",
                what=f"action_{i}",
                why=f"Reason {i}",
                evidence_ids=[f"ev_{i}"],
                incident_id="inc-tamper-del",
            )

        # Tamper: Delete line 2 (sequence 2)
        lines = self.log_file.read_text(encoding="utf-8").splitlines()
        del lines[2]
        self.log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Verify integrity detects deletion
        is_valid, msg = self.audit.verify_integrity()
        self.assertFalse(is_valid, "Deleting a line must break the hash chain")
        self.assertTrue("non-contiguous sequence" in msg or "broken hash chain" in msg)

    def test_tamper_detection_genesis_line_deleted(self):
        """Deleting the first (genesis) line is immediately detected."""
        for i in range(3):
            self.audit.log_decision(
                who=f"agent_{i}",
                what=f"action_{i}",
                why=f"Reason {i}",
                evidence_ids=[f"ev_{i}"],
                incident_id="inc-tamper-genesis",
            )

        lines = self.log_file.read_text(encoding="utf-8").splitlines()
        del lines[0]  # Delete genesis entry
        self.log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        is_valid, msg = self.audit.verify_integrity()
        self.assertFalse(is_valid, "Deleting genesis line must be detected")
        self.assertTrue("non-contiguous sequence" in msg or "broken hash chain" in msg)

    def test_tamper_detection_line_inserted(self):
        """Inserting an unauthorized line into the log is immediately detected."""
        for i in range(3):
            self.audit.log_decision(
                who=f"agent_{i}",
                what=f"action_{i}",
                why=f"Reason {i}",
                evidence_ids=[f"ev_{i}"],
                incident_id="inc-tamper-ins",
            )

        lines = self.log_file.read_text(encoding="utf-8").splitlines()
        fake_entry = AuditEntry(
            sequence=1,
            timestamp="2026-11-24T12:00:00Z",
            who="attacker",
            what="unauthorized_grant",
            why="forged",
            evidence_ids=[],
            incident_id="inc-tamper-ins",
            prev_hash=GENESIS_HASH,
        )
        fake_entry.entry_hash = fake_entry.compute_hash()
        lines.insert(1, fake_entry.to_json())
        self.log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        is_valid, msg = self.audit.verify_integrity()
        self.assertFalse(is_valid, "Inserting a line must be detected")
        self.assertTrue("broken hash chain" in msg or "non-contiguous sequence" in msg)

    def test_persistence_and_reopen_continues_hash_chain(self):
        """Criterion 7: Reopening an existing audit log file seamlessly resumes the hash chain."""
        e0 = self.audit.log_decision(
            who="agent_1",
            what="action_1",
            why="Reason 1",
            evidence_ids=["ev_1"],
            incident_id="inc-persist",
        )

        # Open a new instance pointing to the same file (simulating service restart)
        reopened_audit = AuditLogger(self.log_file)
        self.assertEqual(reopened_audit._last_sequence, 0)
        self.assertEqual(reopened_audit._last_hash, e0.entry_hash)

        # Log next decision from new instance
        e1 = reopened_audit.log_decision(
            who="agent_2",
            what="action_2",
            why="Reason 2",
            evidence_ids=["ev_2"],
            incident_id="inc-persist",
        )

        self.assertEqual(e1.sequence, 1)
        self.assertEqual(e1.prev_hash, e0.entry_hash)

        # Verify integrity of entire multi-session log
        is_valid, msg = reopened_audit.verify_integrity()
        self.assertTrue(is_valid, msg)
        self.assertIn("2 entries intact", msg)

    def test_filter_entries(self):
        """Filtering by incident, actor, or status."""
        self.audit.log_decision(
            who="agent_a",
            what="action_1",
            why="Reason 1",
            evidence_ids=[],
            incident_id="inc-1",
            status="EXECUTED",
        )
        self.audit.log_decision(
            who="agent_b",
            what="action_2",
            why="Reason 2",
            evidence_ids=[],
            incident_id="inc-2",
            status="REJECTED",
        )
        self.audit.log_decision(
            who="agent_a",
            what="action_3",
            why="Reason 3",
            evidence_ids=[],
            incident_id="inc-1",
            status="EXECUTED",
        )

        # Filter by incident
        inc1_entries = self.audit.filter_entries(incident_id="inc-1")
        self.assertEqual(len(inc1_entries), 2)

        # Filter by actor
        agent_b_entries = self.audit.filter_entries(who="agent_b")
        self.assertEqual(len(agent_b_entries), 1)

        # Filter by status
        rejected_entries = self.audit.filter_entries(status="REJECTED")
        self.assertEqual(len(rejected_entries), 1)


if __name__ == "__main__":
    unittest.main()
