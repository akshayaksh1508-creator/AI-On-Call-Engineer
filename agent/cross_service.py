"""Cross-Service Dependency & Multi-Hop RCA Analyzer (Day 8 Task B3).

Traces downstream service dependencies across the microservice topology
(`gateway -> orders -> payments`) when upstream symptoms (e.g. 502/504)
originate in a downstream culprit service, producing ranked Top-3 hypotheses.

Owner: Person B (Brain & Trust)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


DEFAULT_SERVICE_EDGES: List[Tuple[str, str]] = [
    ("gateway", "orders"),
    ("orders", "payments"),
    ("orders", "postgres"),
]


@dataclass
class CrossServiceHypothesis:
    """Ranked RCA hypothesis for a cross-service incident."""

    rank: int
    culprit_service: str
    cause: str
    score: float
    evidence_ids: List[str]


class CrossServiceAnalyzer:
    """Performs BFS downstream trace and log/change correlation across services."""

    def __init__(self, edges: Optional[Sequence[Tuple[str, str]]] = None) -> None:
        self.edges = list(edges) if edges is not None else list(DEFAULT_SERVICE_EDGES)

    def downstream_services(self, start_service: str) -> List[str]:
        """Return ordered downstream services reachable from `start_service` via BFS."""
        adj: Dict[str, List[str]] = {}
        for src, dst in self.edges:
            adj.setdefault(src, []).append(dst)

        visited: List[str] = []
        queue: deque[str] = deque([start_service])
        seen = {start_service}

        while queue:
            curr = queue.popleft()
            visited.append(curr)
            for nxt in adj.get(curr, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return visited

    def rank_culprits(
        self,
        *,
        symptom_service: str,
        logs_by_service: Dict[str, Sequence[str]],
        changes_by_service: Optional[Dict[str, Sequence[str]]] = None,
    ) -> List[CrossServiceHypothesis]:
        """Score each reachable service using downstream error signals & recent changes."""
        chain = self.downstream_services(symptom_service)
        changes_map = changes_by_service or {}
        scored: List[tuple[float, str, str, List[str]]] = []

        error_markers = (
            "error", "exception", "500", "502", "504", "timeout",
            "validation", "keyerror", "exhausted", "retry", "rejected",
            "declined", "starvation", "deadlock",
        )

        for hop_idx, svc in enumerate(chain):
            svc_logs = logs_by_service.get(svc, [])
            svc_changes = changes_map.get(svc, [])

            err_hits = [
                line for line in svc_logs
                if any(m in line.lower() for m in error_markers)
            ]
            score = 0.0
            if err_hits:
                # Downstream error logs with specific failure traces outrank mere upstream 502/504 symptoms
                is_downstream_root = (
                    hop_idx > 0
                    and any(
                        kw in " ".join(err_hits).lower()
                        for kw in ("validation", "timeout", "webhook", "keyerror", "exception", "exhausted", "rejected")
                    )
                )
                score += 0.55 + (0.25 if is_downstream_root else 0.0)
                score += min(0.15, 0.05 * len(err_hits))
            if svc_changes:
                score += 0.15

            # Slight tie-break for non-generic symptom services when downstream errors exist
            if svc == symptom_service and not err_hits:
                score += 0.05

            cause = (
                err_hits[0]
                if err_hits
                else f"Potential cascading fault in {svc} affecting {symptom_service}"
            )
            ev_ids = [f"ev_{svc}_log_{i+1}" for i in range(max(1, min(2, len(err_hits))))]
            scored.append((round(min(1.0, score), 4), svc, cause, ev_ids))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            CrossServiceHypothesis(
                rank=idx + 1,
                culprit_service=svc,
                cause=cause,
                score=sc,
                evidence_ids=eids,
            )
            for idx, (sc, svc, cause, eids) in enumerate(scored[:3])
        ]
