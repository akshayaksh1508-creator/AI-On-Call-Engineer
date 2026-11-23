"""Autonomous Anomaly Detector and Deduplicating Incident Engine.

Owner: Person A (Systems & Proof)
Monitors microservice telemetry every 10 seconds:
1. Opens an Incident when error rate is > 5% for >= 30 seconds
2. Opens an Incident when p95 latency is > 3x baseline for >= 30 seconds
3. Enforces strict deduplication by service and time window (10 minutes)
4. Correlates recent deployments (< 30 minutes prior to incident)
5. Emits valid contracts.models.Incident JSON and notifies subscribers.
"""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.error
import urllib.request

from contracts.models import Incident
from detector.evaluator import (
    EvaluationResult,
    MetricObservation,
    ServiceTelemetryEvaluator,
    parse_prometheus_text,
)

logger = logging.getLogger("detector.engine")

DEFAULT_SERVICES = ["gateway", "orders", "payments"]
DEFAULT_SERVICE_PORTS = {
    "gateway": 8080,
    "orders": 8081,
    "payments": 8082,
}


class IncidentDetector:
    """Continuously evaluates microservice telemetry and emits deduplicated Incidents."""

    def __init__(
        self,
        services: Optional[List[str]] = None,
        poll_interval: float = 10.0,
        error_rate_threshold: float = 0.05,        # 5% error rate
        latency_multiplier_threshold: float = 3.0,   # 3x baseline
        baseline_p95_latency: float = 0.05,         # 50ms default baseline
        sustained_window_seconds: float = 30.0,     # 30s sustained duration
        dedupe_window_seconds: float = 600.0,       # 10 minutes dedupe window
        prometheus_url: Optional[str] = None,
        changes_path: Optional[Path] = None,
        incidents_dir: Optional[Path] = None,
        on_incident_opened: Optional[Callable[[Incident], None]] = None,
    ):
        self.services = services or DEFAULT_SERVICES
        self.poll_interval = poll_interval
        self.error_rate_threshold = error_rate_threshold
        self.latency_multiplier_threshold = latency_multiplier_threshold
        self.baseline_p95_latency = baseline_p95_latency
        self.sustained_window_seconds = sustained_window_seconds
        self.dedupe_window_seconds = dedupe_window_seconds
        self.prometheus_url = prometheus_url or os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
        self.on_incident_opened = on_incident_opened

        # Path configurations
        project_root = Path(__file__).resolve().parent.parent
        self.changes_path = changes_path or (project_root / "data" / "changes.json")
        self.incidents_dir = incidents_dir or (project_root / "data" / "incidents")
        self.incidents_dir.mkdir(parents=True, exist_ok=True)
        self.active_incidents_file = self.incidents_dir.parent / "active_incidents.json"

        # Per-service evaluators
        self.evaluators: Dict[str, ServiceTelemetryEvaluator] = {
            svc: ServiceTelemetryEvaluator(
                service=svc,
                error_rate_threshold=self.error_rate_threshold,
                latency_multiplier_threshold=self.latency_multiplier_threshold,
                baseline_p95_latency=self.baseline_p95_latency,
                sustained_window_seconds=self.sustained_window_seconds,
            )
            for svc in self.services
        }

        # Deduplication tracking: service -> active Incident
        self.active_incidents: Dict[str, Incident] = {}
        # Incident history: all incidents opened during this detector lifecycle
        self.all_incidents: List[Incident] = []

        # Background thread control
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def evaluate_sample(
        self,
        service: str,
        sample: MetricObservation,
        now: Optional[float] = None,
    ) -> Tuple[Optional[Incident], bool]:
        """Feed a metric observation into a service evaluator and check if an Incident should be opened.
        
        Returns:
            (incident, is_new)
            - incident is None if healthy
            - is_new is True if a new incident was opened, False if deduplicated against active incident
        """
        if service not in self.evaluators:
            self.evaluators[service] = ServiceTelemetryEvaluator(
                service=service,
                error_rate_threshold=self.error_rate_threshold,
                latency_multiplier_threshold=self.latency_multiplier_threshold,
                baseline_p95_latency=self.baseline_p95_latency,
                sustained_window_seconds=self.sustained_window_seconds,
            )

        evaluator = self.evaluators[service]
        result: EvaluationResult = evaluator.add_observation(sample)

        eval_ts = now or sample.timestamp

        if not result.is_anomalous:
            # Service is healthy. If there was an active incident that was resolved, mark it
            if service in self.active_incidents:
                active = self.active_incidents[service]
                # If error rate dropped below 1% and latency recovered, mark resolved
                if result.error_rate < 0.01 and result.p95_latency < (self.baseline_p95_latency * 1.5):
                    logger.info("Service '%s' recovered. Closing active incident %s", service, active.id)
                    active.status = "resolved"
                    self._persist_incident(active)
                    del self.active_incidents[service]
            return None, False

        # Service is anomalous! Check deduplication window
        if service in self.active_incidents:
            existing = self.active_incidents[service]
            started_epoch = self._iso_to_epoch(existing.started_at)
            elapsed = eval_ts - started_epoch

            if elapsed < self.dedupe_window_seconds and existing.status in ("open", "investigating", "mitigating"):
                # Deduplicated: append any newly emerging alerts/symptoms to existing incident
                updated = False
                for alert in result.alerts:
                    if alert not in existing.alerts:
                        existing.alerts.append(alert)
                        updated = True
                for symptom in result.symptoms:
                    if symptom not in existing.symptoms:
                        existing.symptoms.append(symptom)
                        updated = True
                if updated:
                    self._persist_incident(existing)
                logger.info(
                    "Deduplicated anomalous signal for '%s' against active incident %s (elapsed: %.1fs)",
                    service,
                    existing.id,
                    elapsed,
                )
                return existing, False

        # Open a new Incident!
        incident_id = f"inc_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{service}"
        started_at = datetime.fromtimestamp(eval_ts, tz=timezone.utc).isoformat()

        # Correlate recent changes in the 30 minutes prior to incident start
        recent_changes = self._find_recent_changes(service=service, incident_time_epoch=eval_ts)

        incident = Incident(
            id=incident_id,
            service=service,
            started_at=started_at,
            symptoms=result.symptoms,
            alerts=result.alerts,
            recent_changes=recent_changes,
            status="open",
        )

        self.active_incidents[service] = incident
        self.all_incidents.append(incident)
        self._persist_incident(incident)

        logger.warning(
            "Opened new incident %s on '%s' (symptoms: %s, alerts: %s)",
            incident.id,
            service,
            incident.symptoms,
            incident.alerts,
        )

        if self.on_incident_opened:
            try:
                self.on_incident_opened(incident)
            except Exception as exc:
                logger.error("Error in on_incident_opened callback: %s", exc)

        return incident, True

    def check_once(self) -> List[Incident]:
        """Perform a single scrape & evaluation across all configured services.
        
        Returns:
            List of newly opened Incident objects.
        """
        new_incidents: List[Incident] = []
        for service in self.services:
            sample = self._scrape_service_metrics(service)
            if sample:
                incident, is_new = self.evaluate_sample(service, sample)
                if incident and is_new:
                    new_incidents.append(incident)
        return new_incidents

    def _scrape_service_metrics(self, service: str) -> Optional[MetricObservation]:
        """Scrapes telemetry either via Prometheus PromQL or direct microservice endpoint."""
        # 1. Try direct microservice /metrics endpoint
        port = DEFAULT_SERVICE_PORTS.get(service)
        if port:
            endpoint_url = f"http://localhost:{port}/metrics"
            try:
                req = urllib.request.Request(endpoint_url, headers={"User-Agent": "NightShift-Detector"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    if resp.getcode() == 200:
                        text = resp.read().decode("utf-8")
                        return parse_prometheus_text(text, service)
            except Exception:
                pass

        # 2. Try Prometheus PromQL API if server is running
        try:
            promql_url = f"{self.prometheus_url}/api/v1/query"
            query_total = f'sum(http_requests_total{{service="{service}"}})'
            query_errors = f'sum(http_requests_total{{service="{service}",status=~"5.."}})'

            total_val = self._query_promql(promql_url, query_total)
            error_val = self._query_promql(promql_url, query_errors)

            if total_val is not None:
                return MetricObservation(
                    timestamp=time.time(),
                    total_requests=total_val,
                    errors_5xx=error_val or 0.0,
                )
        except Exception:
            pass

        return None

    def _query_promql(self, prom_api_url: str, query: str) -> Optional[float]:
        """Execute instant PromQL query against Prometheus HTTP API."""
        try:
            params = urllib.parse.urlencode({"query": query})
            url = f"{prom_api_url}?{params}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "success":
                    result = data.get("data", {}).get("result", [])
                    if result and len(result) > 0:
                        val = result[0].get("value", [0, "0"])[1]
                        return float(val)
        except Exception:
            pass
        return None

    def _find_recent_changes(self, service: str, incident_time_epoch: float) -> List[str]:
        """Query changes.json for deploys or config modifications within 30 minutes before incident start."""
        recent: List[str] = []
        if not self.changes_path.exists():
            return recent

        try:
            content = self.changes_path.read_text(encoding="utf-8").strip()
            if not content:
                return recent
            changes_data = json.loads(content)
            cutoff_epoch = incident_time_epoch - (30 * 60) # 30 minutes prior

            for chg in changes_data:
                chg_time = chg.get("timestamp")
                chg_svc = chg.get("service")
                if not chg_time:
                    continue
                epoch = self._iso_to_epoch(chg_time)
                # Check if change occurred in the 30-minute window prior to incident
                if cutoff_epoch <= epoch <= (incident_time_epoch + 60):
                    chg_id = chg.get("id", "unknown_change")
                    version = chg.get("version", "")
                    label = f"{chg_id} ({version})" if version else chg_id
                    if label not in recent:
                        recent.append(label)
        except Exception as exc:
            logger.warning("Failed to read recent changes from %s: %s", self.changes_path, exc)

        return recent

    def _persist_incident(self, incident: Incident) -> None:
        """Persist incident JSON to disk."""
        try:
            out_file = self.incidents_dir / f"{incident.id}.json"
            out_file.write_text(json.dumps(incident.model_dump(), indent=2), encoding="utf-8")

            # Update active incidents manifest
            active_data = {
                svc: inc.model_dump() for svc, inc in self.active_incidents.items()
            }
            self.active_incidents_file.write_text(json.dumps(active_data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to persist incident %s: %s", incident.id, exc)

    def _iso_to_epoch(self, iso_str: str) -> float:
        """Parse ISO 8601 string to UNIX timestamp."""
        try:
            # Handle Python 3.11+ fromisoformat
            clean_str = iso_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_str)
            return dt.timestamp()
        except Exception:
            return time.time()

    def start(self) -> None:
        """Start background polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="detector-loop")
        self._thread.start()
        logger.info("IncidentDetector started background polling loop (interval: %.1fs)", self.poll_interval)

    def stop(self) -> None:
        """Stop background polling thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("IncidentDetector stopped.")

    def _run_loop(self) -> None:
        """Continuous polling loop."""
        while self._running:
            try:
                self.check_once()
            except Exception as exc:
                logger.error("Unexpected error in detector check_once: %s", exc)
            time.sleep(self.poll_interval)
