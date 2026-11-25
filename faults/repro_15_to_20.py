"""Deterministic reproduction & ground-truth verification for Faults 15-20 (Day 7 Task A2).

Covers resource and cross-service faults:
  - fault_015_disk_full (resource)
  - fault_016_slow_query_missing_index (resource)
  - fault_017_symptom_gw_cause_payments (cross_service)
  - fault_018_retry_storm (cross_service)
  - fault_019_upstream_schema_change (cross_service)
  - fault_020_dependency_timeout_cascade (cross_service)

Each fault can be injected into an isolated runtime state, reproduced deterministically
multiple times in a row, and cleanly reverted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


FAULTS_15_TO_20: Dict[str, Dict[str, Any]] = {
    "fault_015_disk_full": {
        "fault_id": "fault_015_disk_full",
        "spec_id": "fault_15",
        "title": "Disk Volume Full from Verbose Debug Logs",
        "category": "resource",
        "difficulty": "hard",
        "target_service": "orders",
        "symptom_service": "orders",
        "culprit_change": "infra_20261123_001",
        "culprit_commit": None,
        "root_cause": "Unrotated DEBUG payload logging exhausts partition disk capacity",
        "visible_symptoms": [
            "Orders fails on write operations with OSError: [Errno 28] No space left on device",
            "Disk utilization metrics reach 100%",
        ],
        "expected_fix": "Disable verbose DEBUG logging and enable log rotation on orders",
        "expected_fix_type": "config",
        "alternative_fix_type": "rollback",
        "risk_tier": "T1",
        "env": {"orders": {"ORDERS_LOG_LEVEL": "DEBUG", "ORDERS_DISK_SIMULATE_FULL": "1"}},
        "keywords": ["disk", "space", "errno 28", "debug", "logging", "orders"],
    },
    "fault_016_slow_query_missing_index": {
        "fault_id": "fault_016_slow_query_missing_index",
        "spec_id": "fault_16",
        "title": "Missing DB Index on customer_id",
        "category": "resource",
        "difficulty": "medium",
        "target_service": "orders",
        "symptom_service": "orders",
        "culprit_change": "dep_20261123_v1.0.11",
        "culprit_commit": "f5a7b9c1",
        "root_cause": "Full sequential table scan across 500k rows due to missing customer_id index",
        "visible_symptoms": [
            "Query latency spikes from 8ms to 4,200ms",
            "Postgres CPU utilization reaches 95%",
        ],
        "expected_fix": "Add B-tree index on orders(customer_id)",
        "expected_fix_type": "patch",
        "alternative_fix_type": "rollback",
        "risk_tier": "T3",
        "env": {"orders": {"ORDERS_DB_MISSING_INDEX": "1", "ORDERS_DB_QUERY_LATENCY_MS": "4200"}},
        "keywords": ["index", "customer_id", "slow query", "latency", "postgres", "orders"],
    },
    "fault_017_symptom_gw_cause_payments": {
        "fault_id": "fault_017_symptom_gw_cause_payments",
        "spec_id": "fault_17",
        "title": "Gateway 502 Outage Caused by Payments Deploy",
        "category": "cross_service",
        "difficulty": "hard",
        "target_service": "payments",
        "symptom_service": "gateway",
        "culprit_change": "dep_20261123_v1.0.12",
        "culprit_commit": "e6f8a0b2",
        "root_cause": "Validation failure in Payments deploy rejects orders, cascading 502 to Gateway",
        "visible_symptoms": [
            "Gateway alerts on High5xxErrorRate (45% error rate)",
            "Orders service reports 200 health but fails checkout requests",
            "Root error trace located exclusively in payments logs",
        ],
        "expected_fix": "Fix validation check in payments or rollback dep_20261123_v1.0.12",
        "expected_fix_type": "patch",
        "alternative_fix_type": "rollback",
        "risk_tier": "T2",
        "env": {"payments": {"PAYMENTS_STRICT_VALIDATION_FAIL": "1"}},
        "keywords": ["gateway", "502", "payments", "validation", "cascade"],
    },
    "fault_018_retry_storm": {
        "fault_id": "fault_018_retry_storm",
        "spec_id": "fault_18",
        "title": "Infinite Retry Storm Multiplies Load 12x",
        "category": "cross_service",
        "difficulty": "hard",
        "target_service": "gateway",
        "symptom_service": "orders",
        "culprit_change": "cfg_20261123_005",
        "culprit_commit": None,
        "root_cause": "Gateway retry policy set to 10 retries with 0s backoff, causing cascading downstream flood",
        "visible_symptoms": [
            "Normal 10 rps ingress traffic creates 120 rps downstream traffic to Orders",
            "Orders thread pool and CPU fully saturated",
        ],
        "expected_fix": "Revert gateway retry policy to max 2 retries with exponential backoff",
        "expected_fix_type": "config",
        "alternative_fix_type": "rollback",
        "risk_tier": "T1",
        "env": {"gateway": {"GATEWAY_MAX_RETRIES": "10", "GATEWAY_RETRY_BACKOFF_MS": "0"}},
        "keywords": ["retry", "storm", "backoff", "gateway", "orders", "saturation"],
    },
    "fault_019_upstream_schema_change": {
        "fault_id": "fault_019_upstream_schema_change",
        "spec_id": "fault_19",
        "title": "API Field Rename Without Backwards Compatibility",
        "category": "cross_service",
        "difficulty": "hard",
        "target_service": "orders",
        "symptom_service": "gateway",
        "culprit_change": "dep_20261123_v1.0.13",
        "culprit_commit": "a7b9c1d3",
        "root_cause": "Orders renamed 'total' to 'total_amount_cents' without backwards compatibility",
        "visible_symptoms": [
            "Gateway returns 422 or 502 on order creation",
            "Gateway log indicates KeyError: 'total'",
        ],
        "expected_fix": "Restore backwards-compatible 'total' field in orders API response",
        "expected_fix_type": "patch",
        "alternative_fix_type": "rollback",
        "risk_tier": "T2",
        "env": {"orders": {"ORDERS_RESPONSE_SCHEMA_V2": "1"}},
        "keywords": ["schema", "total", "total_amount_cents", "keyerror", "orders", "gateway"],
    },
    "fault_020_dependency_timeout_cascade": {
        "fault_id": "fault_020_dependency_timeout_cascade",
        "spec_id": "fault_20",
        "title": "External Synchronous Webhook Starvation",
        "category": "cross_service",
        "difficulty": "hard",
        "target_service": "payments",
        "symptom_service": "gateway",
        "culprit_change": "dep_20261123_v1.0.14",
        "culprit_commit": "c9d1e3f5",
        "root_cause": "Synchronous external webhook call without timeout cap starves worker threads",
        "visible_symptoms": [
            "Payments latency reaches 15s, exhausting worker sockets",
            "Upstream orders and gateway return 504 timeouts",
        ],
        "expected_fix": "Add explicit 2s timeout cap or async dispatch to external webhook in payments",
        "expected_fix_type": "patch",
        "alternative_fix_type": "rollback",
        "risk_tier": "T2",
        "env": {"payments": {"PAYMENTS_WEBHOOK_TIMEOUT_MS": "0", "PAYMENTS_WEBHOOK_DELAY_MS": "15000"}},
        "keywords": ["webhook", "timeout", "504", "payments", "gateway", "starvation"],
    },
}


@dataclass
class Fault15To20Harness:
    """In-memory deterministic simulation harness for reproducing Faults 15-20."""

    active_faults: List[str] = field(default_factory=list)

    def inject(self, fault_id: str) -> Dict[str, Any]:
        if fault_id not in FAULTS_15_TO_20:
            raise KeyError(f"Unknown fault_id {fault_id!r}")
        if fault_id not in self.active_faults:
            self.active_faults.append(fault_id)
        return {"fault_id": fault_id, "injected": True, "env": FAULTS_15_TO_20[fault_id]["env"]}

    def revert(self, fault_id: str) -> Dict[str, Any]:
        if fault_id in self.active_faults:
            self.active_faults.remove(fault_id)
        return {"fault_id": fault_id, "reverted": True}

    def revert_all(self) -> None:
        self.active_faults.clear()

    def reproduce(self, fault_id: str) -> Dict[str, Any]:
        """Execute deterministic failing-request reproduction for fault 15-20.

        Returns a dict with `reproduced` (True if fault signature observed, False if healthy),
        `status_code`, `error`, and `metrics`.
        """
        if fault_id not in FAULTS_15_TO_20:
            raise KeyError(f"Unknown fault_id {fault_id!r}")

        if fault_id not in self.active_faults:
            return {
                "fault_id": fault_id,
                "reproduced": False,
                "status_code": 200,
                "error": None,
                "metrics": {"error_rate": 0.002, "p95_latency_ms": 25.0, "disk_usage_pct": 35.0},
            }

        if fault_id == "fault_015_disk_full":
            return {
                "fault_id": fault_id,
                "reproduced": True,
                "status_code": 500,
                "error": "OSError: [Errno 28] No space left on device",
                "metrics": {"error_rate": 0.45, "disk_usage_pct": 100.0},
            }
        if fault_id == "fault_016_slow_query_missing_index":
            return {
                "fault_id": fault_id,
                "reproduced": True,
                "status_code": 200,
                "error": "Sequential table scan: query latency 4200ms exceeds 500ms SLA",
                "metrics": {"p95_latency_ms": 4200.0, "postgres_cpu_pct": 95.0, "error_rate": 0.08},
            }
        if fault_id == "fault_017_symptom_gw_cause_payments":
            return {
                "fault_id": fault_id,
                "reproduced": True,
                "status_code": 502,
                "error": "Gateway 502 Bad Gateway: downstream payments validation rejected order",
                "metrics": {"gateway_5xx_rate": 0.45, "orders_health": 200, "error_rate": 0.45},
            }
        if fault_id == "fault_018_retry_storm":
            return {
                "fault_id": fault_id,
                "reproduced": True,
                "status_code": 503,
                "error": "Orders thread pool exhausted: 120 rps downstream from 10 rps ingress (10 retries, 0s backoff)",
                "metrics": {"ingress_rps": 10.0, "downstream_rps": 120.0, "error_rate": 0.35},
            }
        if fault_id == "fault_019_upstream_schema_change":
            return {
                "fault_id": fault_id,
                "reproduced": True,
                "status_code": 502,
                "error": "KeyError: 'total' in gateway order response parser (orders emitted 'total_amount_cents')",
                "metrics": {"gateway_5xx_rate": 0.40, "error_rate": 0.40},
            }
        if fault_id == "fault_020_dependency_timeout_cascade":
            return {
                "fault_id": fault_id,
                "reproduced": True,
                "status_code": 504,
                "error": "Gateway 504 Timeout: payments webhook blocked worker threads for 15000ms",
                "metrics": {"p95_latency_ms": 15000.0, "gateway_504_rate": 0.50, "error_rate": 0.50},
            }

        raise AssertionError(f"Unhandled fault_id {fault_id}")
