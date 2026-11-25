"""Unit tests for IncidentMemoryStore & search_past_incidents (Day 7 Tasks B1 & B2).

Verifies:
1. Task B1: SQLite save & load round trip preserves all fields.
2. Task B1: Duplicate incidents (matching ID or normalized signature) are merged cleanly.
3. Task B2: Repeated incident retrieves its predecessor at rank 1.
4. Task B2: Unrelated incident returns nothing above the similarity threshold.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory import IncidentMemoryRecord, IncidentMemoryStore, search_past_incidents


class TestMemoryStoreAndRetrieval(unittest.TestCase):
    """Test suite for Day 7 Tasks B1 and B2."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "nightshift_memory.sqlite"
        self.store = IncidentMemoryStore(self.db_path)

    def tearDown(self) -> None:
        self.store.close()
        self.tmp.cleanup()

    def test_01_sqlite_save_and_load_round_trip(self) -> None:
        """Exit criterion B1: Save and load round trip on persistent SQLite file."""
        rec = IncidentMemoryRecord(
            incident_id="inc_001",
            fault_id="fault_001_bad_deploy",
            service="orders",
            category="code",
            symptom_signature="HTTP 500 TypeError NoneType object is not subscriptable discount code",
            cause="Missing null check when optional discount dict is omitted from POST /orders",
            fix="Use discount.get('code') if isinstance(discount, dict) else None",
            evidence_summary="orders log TypeError at app.py:82; commit c0ffee14a",
            evidence_ids=["ev_log_001", "ev_commit_001"],
        )
        saved = self.store.save(rec)
        self.assertEqual(saved.incident_id, "inc_001")
        self.assertEqual(saved.occurrence_count, 1)

        # Re-open SQLite DB from disk to verify real persistence
        reopened = IncidentMemoryStore(self.db_path)
        try:
            loaded = reopened.load("inc_001")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.fault_id, "fault_001_bad_deploy")
            self.assertEqual(loaded.category, "code")
            self.assertEqual(loaded.service, "orders")
            self.assertEqual(loaded.cause, rec.cause)
            self.assertEqual(loaded.fix, rec.fix)
            self.assertEqual(loaded.evidence_summary, rec.evidence_summary)
            self.assertEqual(loaded.evidence_ids, ["ev_log_001", "ev_commit_001"])
        finally:
            reopened.close()

    def test_02_duplicate_incidents_are_merged(self) -> None:
        """Exit criterion B1: Duplicate incidents merge into one record with incremented count."""
        rec1 = IncidentMemoryRecord(
            incident_id="inc_dup_1",
            fault_id="fault_003_wrong_status_code",
            service="payments",
            category="code",
            symptom_signature="Payments returns HTTP 200 DECLINED instead of 402",
            cause="Declined payments return 200 OK instead of HTTP 402",
            fix="Raise HTTPException(status_code=402) on declined card",
            evidence_summary="payments log DECLINED payload with 200",
            evidence_ids=["ev_log_p1"],
        )
        rec2 = IncidentMemoryRecord(
            incident_id="inc_dup_2",
            fault_id="fault_003_wrong_status_code",
            service="payments",
            category="code",
            symptom_signature="Payments returns HTTP 200 DECLINED instead of 402!",
            cause="Declined payments return 200 OK instead of HTTP 402",
            fix="Raise HTTPException(status_code=402) on declined card",
            evidence_summary="reconciliation mismatch in ledger",
            evidence_ids=["ev_log_p2"],
        )

        self.store.save(rec1)
        merged = self.store.save(rec2)

        self.assertEqual(self.store.count(), 1, "Duplicate signature must merge into single row")
        self.assertEqual(merged.occurrence_count, 2)
        self.assertEqual(merged.evidence_ids, ["ev_log_p1", "ev_log_p2"])
        self.assertIn("reconciliation mismatch", merged.evidence_summary)

    def test_03_repeated_incident_retrieves_predecessor_at_rank_1(self) -> None:
        """Exit criterion B2: Repeated incident retrieves predecessor at rank 1."""
        self.store.save(
            IncidentMemoryRecord(
                incident_id="inc_mem_1",
                fault_id="fault_001_bad_deploy",
                service="orders",
                category="code",
                symptom_signature="HTTP 500 TypeError NoneType object subscriptable discount",
                cause="Missing null check for optional discount in create_order",
                fix="Guard discount.get('code') when discount is None",
                evidence_summary="TypeError in orders/app.py",
                evidence_ids=["ev_1"],
            )
        )
        self.store.save(
            IncidentMemoryRecord(
                incident_id="inc_mem_2",
                fault_id="fault_015_disk_full",
                service="orders",
                category="resource",
                symptom_signature="OSError Errno 28 No space left on device debug logs",
                cause="Unrotated DEBUG logging filled disk partition to 100%",
                fix="Disable DEBUG logging and enable log rotation",
                evidence_summary="disk utilization 100%",
                evidence_ids=["ev_2"],
            )
        )
        self.store.save(
            IncidentMemoryRecord(
                incident_id="inc_mem_3",
                fault_id="fault_018_retry_storm",
                service="gateway",
                category="cross_service",
                symptom_signature="120 rps downstream retry storm 0s backoff thread pool saturated",
                cause="Gateway retry policy set to 10 retries with 0s backoff",
                fix="Restore max 2 retries with exponential backoff",
                evidence_summary="gateway 10 retries config",
                evidence_ids=["ev_3"],
            )
        )

        hits = search_past_incidents(
            self.store,
            query="Orders crashing with HTTP 500 TypeError NoneType discount subscriptable",
            category="code",
            service="orders",
            threshold=0.25,
            limit=3,
        )
        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["incident_id"], "inc_mem_1", "Predecessor must be rank 1")
        self.assertGreaterEqual(hits[0]["score"], 0.25)

    def test_04_unrelated_incident_returns_nothing_above_threshold(self) -> None:
        """Exit criterion B2: Unrelated incident returns empty list above threshold."""
        self.store.save(
            IncidentMemoryRecord(
                incident_id="inc_mem_1",
                fault_id="fault_001_bad_deploy",
                service="orders",
                category="code",
                symptom_signature="HTTP 500 TypeError NoneType object subscriptable discount",
                cause="Missing null check for optional discount in create_order",
                fix="Guard discount.get('code') when discount is None",
                evidence_summary="TypeError in orders/app.py",
                evidence_ids=["ev_1"],
            )
        )

        unrelated_hits = search_past_incidents(
            self.store,
            query="Kubernetes TLS certificate expired on ingress load balancer",
            category="resource",
            service="payments",
            threshold=0.25,
            limit=3,
        )
        self.assertEqual(unrelated_hits, [], "Unrelated query must return nothing above threshold")


if __name__ == "__main__":
    unittest.main()
