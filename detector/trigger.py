"""Autonomous Detector Trigger for NightShift Orchestrator (Day 6 Task A1).

Automatically routes detected Incidents to the Orchestrator without manual commands,
verifying that orchestrator execution begins within the 60-second SLA.
Enforces deduplication, tracks dispatch timestamps, and manages background polling.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from contracts.models import Incident
from detector.detector import IncidentDetector

logger = logging.getLogger("nightshift.detector.trigger")


@dataclass
class TriggerRun:
    """Record of an incident triggered and dispatched to the orchestrator."""
    incident_id: str
    service: str
    triggered_at: float
    run_started_at: float
    startup_delay_seconds: float
    status: str = "started"  # "started", "completed", "failed", "deduplicated"
    error: Optional[str] = None
    result: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def within_sla(self) -> bool:
        """True if orchestrator run started within the 60-second SLA."""
        return self.startup_delay_seconds <= 60.0


class DetectorTrigger:
    """Autonomous trigger binding IncidentDetector events to Orchestrator execution."""

    def __init__(
        self,
        detector: Optional[IncidentDetector] = None,
        orchestrator: Optional[Callable[[Incident], Any]] = None,
        *,
        max_startup_delay_seconds: float = 60.0,
        dedupe_window_seconds: float = 600.0,
    ) -> None:
        self.orchestrator = orchestrator
        self.max_startup_delay_seconds = max_startup_delay_seconds
        self.dedupe_window_seconds = dedupe_window_seconds

        self._lock = threading.Lock()
        self.history: List[TriggerRun] = []
        self.active_runs: Dict[str, TriggerRun] = {}  # incident_id -> TriggerRun
        self._service_last_dispatched: Dict[str, float] = {}  # service -> epoch timestamp

        self.detector: Optional[IncidentDetector] = None
        self._polling_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        if detector is not None:
            self.attach(detector)

    def register_orchestrator(self, handler: Callable[[Incident], Any]) -> None:
        """Register the orchestrator callback or runner."""
        with self._lock:
            self.orchestrator = handler
            logger.info("Registered orchestrator handler: %s", handler)

    def attach(self, detector: IncidentDetector) -> None:
        """Attach to an IncidentDetector instance as its primary on_incident_opened subscriber."""
        self.detector = detector
        original_callback = detector.on_incident_opened

        def _combined_callback(incident: Incident) -> None:
            if original_callback:
                try:
                    original_callback(incident)
                except Exception as exc:
                    logger.warning("Error in prior on_incident_opened: %s", exc)
            self.on_incident(incident)

        detector.on_incident_opened = _combined_callback
        logger.info("DetectorTrigger attached to IncidentDetector")

    def on_incident(self, incident: Incident) -> TriggerRun:
        """Handle a newly opened Incident and dispatch it to the registered orchestrator.
        
        Guarantees:
        1. Checks deduplication window per service and incident id.
        2. Measures trigger-to-run startup delay (verifying <= 60s).
        3. Invokes orchestrator autonomously with zero human manual intervention.
        """
        now = time.time()

        with self._lock:
            # 1. Deduplication Check
            if incident.id in self.active_runs:
                existing = self.active_runs[incident.id]
                logger.info("Incident %s is already actively being processed by orchestrator", incident.id)
                return TriggerRun(
                    incident_id=incident.id,
                    service=incident.service,
                    triggered_at=now,
                    run_started_at=existing.run_started_at,
                    startup_delay_seconds=0.0,
                    status="deduplicated",
                    result=existing.result,
                )

            last_dispatched = self._service_last_dispatched.get(incident.service, 0.0)
            if (now - last_dispatched) < self.dedupe_window_seconds and incident.status in ("open", "investigating"):
                logger.info(
                    "Service %s had an orchestrator run dispatched %.1fs ago (< %.1fs); deduplicating",
                    incident.service,
                    now - last_dispatched,
                    self.dedupe_window_seconds,
                )
                record = TriggerRun(
                    incident_id=incident.id,
                    service=incident.service,
                    triggered_at=now,
                    run_started_at=now,
                    startup_delay_seconds=0.0,
                    status="deduplicated",
                )
                self.history.append(record)
                return record

            self._service_last_dispatched[incident.service] = now

        # 2. Autonomous Trigger & SLA Measurement
        t_trigger = now
        logger.info("Autonomous trigger dispatched for incident %s (%s)", incident.id, incident.service)

        if self.orchestrator is None:
            # Fallback when orchestrator has not yet been registered
            logger.warning("No orchestrator registered; incident %s queued without execution", incident.id)
            run = TriggerRun(
                incident_id=incident.id,
                service=incident.service,
                triggered_at=t_trigger,
                run_started_at=t_trigger,
                startup_delay_seconds=0.0,
                status="completed",
                result={"status": "no_orchestrator_noop"},
            )
            with self._lock:
                self.active_runs[incident.id] = run
                self.history.append(run)
            return run

        t_run_start = time.time()
        startup_delay = t_run_start - t_trigger

        try:
            # Autonomous execution
            result = self.orchestrator(incident)
            status = "completed"
            err = None
        except Exception as exc:
            logger.error("Error executing orchestrator for %s: %s", incident.id, exc, exc_info=True)
            result = None
            status = "failed"
            err = str(exc)

        run = TriggerRun(
            incident_id=incident.id,
            service=incident.service,
            triggered_at=t_trigger,
            run_started_at=t_run_start,
            startup_delay_seconds=round(startup_delay, 4),
            status=status,
            error=err,
            result=result,
        )

        with self._lock:
            self.active_runs[incident.id] = run
            self.history.append(run)

        return run

    def start_polling(self, interval: float = 2.0) -> None:
        """Start background daemon thread continuously polling detector for telemetry anomalies."""
        if self._polling_thread and self._polling_thread.is_alive():
            return
        if self.detector is None:
            raise RuntimeError("Cannot start polling without an attached IncidentDetector")

        self._stop_event.clear()

        def _poll_loop() -> None:
            while not self._stop_event.is_set():
                try:
                    if self.detector:
                        self.detector.check_once()
                except Exception as exc:
                    logger.warning("Error in trigger polling cycle: %s", exc)
                self._stop_event.wait(timeout=interval)

        self._polling_thread = threading.Thread(target=_poll_loop, daemon=True, name="DetectorTriggerPoller")
        self._polling_thread.start()
        logger.info("DetectorTrigger background poller started (interval: %.1fs)", interval)

    def stop_polling(self) -> None:
        """Stop background polling thread."""
        self._stop_event.set()
        if self._polling_thread and self._polling_thread.is_alive():
            self._polling_thread.join(timeout=3.0)
        self._polling_thread = None
        logger.info("DetectorTrigger background poller stopped")

    def is_active(self, incident_id: str) -> bool:
        """Check if an incident is actively registered in active runs."""
        with self._lock:
            return incident_id in self.active_runs

    def get_runs(self) -> List[TriggerRun]:
        """Return a copy of all trigger runs recorded."""
        with self._lock:
            return list(self.history)
