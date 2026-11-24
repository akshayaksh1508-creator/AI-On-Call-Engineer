"""Unit tests for Autonomous Detector Trigger (Day 6 Task A1).

Verifies:
1. Automatic dispatch from IncidentDetector to Orchestrator without manual commands.
2. SLA criterion: run starts within 60 seconds of anomaly detection.
3. Deduplication: duplicate incidents for the same service within window do not spawn duplicate runs.
4. Error handling: orchestrator exceptions are safely logged and reported in TriggerRun.
5. Background poller continuously monitors and triggers orchestrator when fault is observed.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Ensure repo root is on path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.models import Incident
from detector.detector import IncidentDetector
from detector.evaluator import MetricObservation
from detector.trigger import DetectorTrigger, TriggerRun


class TestDetectorTrigger(unittest.TestCase):
    """Test suite for Day 6 Task A1 DetectorTrigger."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        self.incidents_dir = self.data_dir / "incidents"
        self.changes_file = self.data_dir / "changes.json"
        self.changes_file.write_text("[]", encoding="utf-8")

        self.detector = IncidentDetector(
            services=["orders", "payments"],
            poll_interval=1.0,
            error_rate_threshold=0.05,
            sustained_window_seconds=4.0,  # 4s sustained duration
            dedupe_window_seconds=60.0,
            incidents_dir=self.incidents_dir,
            changes_path=self.changes_file,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_01_automatic_trigger_on_incident(self):
        """DetectorTrigger automatically dispatches incident to registered orchestrator."""
        orchestrator_mock = MagicMock(return_value={"run_id": "run_001", "status": "started"})
        trigger = DetectorTrigger(orchestrator=orchestrator_mock)

        incident = Incident(
            id="inc_20261124_001",
            service="orders",
            started_at="2026-11-24T12:00:00Z",
            symptoms=["error rate > 5%"],
            alerts=["Orders5xxSpike"],
        )

        run = trigger.on_incident(incident)

        self.assertEqual(run.incident_id, "inc_20261124_001")
        self.assertEqual(run.service, "orders")
        self.assertEqual(run.status, "completed")
        self.assertTrue(run.within_sla)
        self.assertLessEqual(run.startup_delay_seconds, 60.0)
        self.assertEqual(run.result, {"run_id": "run_001", "status": "started"})
        orchestrator_mock.assert_called_once_with(incident)

    def test_02_sla_criterion_run_starts_within_60_seconds(self):
        """Exit criterion: A fault causes orchestrator run to start within 60s without manual commands."""
        dispatched_runs = []

        def orchestrator_handler(incident: Incident):
            dispatched_runs.append((incident.id, time.time()))
            return "ok"

        trigger = DetectorTrigger(detector=self.detector, orchestrator=orchestrator_handler)

        t_fault_injected = time.time()

        # Step through samples at 2-second intervals:
        # tick 0: t=0s
        # tick 1: t=2s
        # tick 2: t=4s (sustained >= 4.0s) -> opens incident & triggers orchestrator automatically
        opened_incident = None
        for tick in range(3):
            sample = MetricObservation(
                timestamp=t_fault_injected + (tick * 2.0),
                total_requests=100.0 * (tick + 1),
                errors_5xx=20.0 * (tick + 1),  # 20% error rate > 5% threshold
            )
            inc, is_new = self.detector.evaluate_sample("orders", sample)
            if is_new:
                opened_incident = inc

        self.assertIsNotNone(opened_incident)
        self.assertEqual(len(dispatched_runs), 1)

        inc_id, t_started = dispatched_runs[0]
        self.assertEqual(inc_id, opened_incident.id)

        # Total time from fault injection to orchestrator execution start
        startup_delay = t_started - t_fault_injected
        self.assertLessEqual(startup_delay, 60.0, "Orchestrator run MUST start within 60s SLA")

        runs = trigger.get_runs()
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0].within_sla)
        self.assertLessEqual(runs[0].startup_delay_seconds, 60.0)

    def test_03_strict_deduplication_prevents_duplicate_runs(self):
        """Repeated alerts for the same service within dedupe window do not spawn extra runs."""
        call_count = 0

        def count_orchestrator(incident: Incident):
            nonlocal call_count
            call_count += 1
            return {"count": call_count}

        trigger = DetectorTrigger(
            detector=self.detector,
            orchestrator=count_orchestrator,
            dedupe_window_seconds=300.0,
        )

        inc1 = Incident(
            id="inc_dup_001",
            service="orders",
            started_at="2026-11-24T12:00:00Z",
            symptoms=["5xx errors"],
        )
        inc2 = Incident(
            id="inc_dup_002",
            service="orders",
            started_at="2026-11-24T12:01:00Z",
            symptoms=["5xx errors continue"],
        )

        run1 = trigger.on_incident(inc1)
        self.assertEqual(run1.status, "completed")
        self.assertEqual(call_count, 1)

        # Triggering inc1 again is immediately deduplicated
        run1_again = trigger.on_incident(inc1)
        self.assertEqual(run1_again.status, "deduplicated")
        self.assertEqual(call_count, 1)

        # Triggering a new incident on same service within 300s window is deduplicated
        run2 = trigger.on_incident(inc2)
        self.assertEqual(run2.status, "deduplicated")
        self.assertEqual(call_count, 1)

    def test_04_orchestrator_error_handling(self):
        """Orchestrator exceptions are recorded safely in TriggerRun without crashing."""
        def failing_orchestrator(incident: Incident):
            raise RuntimeError("Orchestrator LLM timeout")

        trigger = DetectorTrigger(orchestrator=failing_orchestrator)
        incident = Incident(
            id="inc_err_001",
            service="payments",
            started_at="2026-11-24T12:00:00Z",
            symptoms=["latency high"],
        )

        run = trigger.on_incident(incident)
        self.assertEqual(run.status, "failed")
        self.assertIn("Orchestrator LLM timeout", run.error or "")
        self.assertIsNone(run.result)

    def test_05_background_poller_detects_and_triggers(self):
        """Background poller monitors telemetry and triggers orchestrator autonomously."""
        invocations = []
        sample_clock = [time.time()]

        def poller_orchestrator(incident: Incident):
            invocations.append(incident.id)
            return "poller_ok"

        # Mock _scrape_service_metrics to return anomalous samples on 'orders'
        tick_counter = 0

        def mock_scrape(service: str):
            nonlocal tick_counter
            if service != "orders":
                return None
            tick_counter += 1
            sample_clock[0] += 2.0
            return MetricObservation(
                timestamp=sample_clock[0],
                total_requests=100.0 * tick_counter,
                errors_5xx=30.0 * tick_counter,  # 30% errors
            )

        self.detector._scrape_service_metrics = mock_scrape
        trigger = DetectorTrigger(detector=self.detector, orchestrator=poller_orchestrator)

        trigger.start_polling(interval=0.05)
        try:
            # Let poller execute enough cycles to satisfy the sustained window
            timeout = time.time() + 3.0
            while len(invocations) == 0 and time.time() < timeout:
                time.sleep(0.05)

            self.assertGreaterEqual(len(invocations), 1)
            self.assertTrue(trigger.is_active(invocations[0]))
        finally:
            trigger.stop_polling()


if __name__ == "__main__":
    unittest.main()
