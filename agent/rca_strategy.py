"""RCA strategy (Day 3, B1 + B4): prompts v1-v3 and deterministic suspect ranking.

Order of investigation enforced by code (not only by the prompt):
  1. recent changes before the incident, 2. service map (upstream first),
  3. error clustering, 4. LLM refines with code / logs / metrics tools.
"""
from __future__ import annotations

from typing import Any, Iterable

from agent.log_clustering import first_error_by_service, has_latency_pattern
from agent.rca_time import to_epoch

CATEGORIES = ("code_bug", "config", "resource", "cross_service", "infra", "unknown")

_BASE = """You are NightShift, an on-call engineer AI. A production incident is open.
Find the root cause. Every claim must cite evidence ids (like E3) that appear in tool results.
Finish by calling the tool submit_hypotheses with up to 3 ranked hypotheses.
Categories: code_bug, config, resource, cross_service, infra, unknown."""

_V2_EXTRA = """
Procedure:
1. FIRST read the recent changes (deploys and config) in the 30 minutes before the incident. Most incidents are caused by a change.
2. Then inspect error logs and, if a change looks suspect, read its diff (git_diff) before concluding.
3. If you have no evidence for a claim, mark it as a guess with low confidence. Never invent evidence ids."""

_V3_EXTRA = """
4. The service showing symptoms is often NOT the cause. Look at the service map and test the upstream
   dependencies of the symptom service. If an upstream service had a change or started failing/slowing
   BEFORE the symptom service, blame the upstream service and use category cross_service.
5. Use the pre-computed suspect ranking as a hint, but verify it with at least one tool call
   (logs, diff or file) before you submit.
6. Confidence guide: 0.85+ only when a change AND matching log evidence agree; 0.5-0.8 when one is
   missing; below 0.4 for guesses. Give a different alternative as hypothesis 2 and 3.
7. Stop as soon as you have strong evidence; do not use more tool calls than needed."""

PROMPTS = {"v1": _BASE, "v2": _BASE + _V2_EXTRA, "v3": _BASE + _V2_EXTRA + _V3_EXTRA}


class ServiceMap:
    """edges: {'from': A, 'to': B} means A calls B (B is upstream/dependency of A)."""

    def __init__(self, nodes: Iterable[str], edges: Iterable[tuple[str, str]]):
        self.nodes = sorted(set(nodes))
        self.calls: dict[str, set[str]] = {}
        for a, b in edges:
            self.calls.setdefault(a, set()).add(b)

    @classmethod
    def from_dict(cls, data: Any) -> "ServiceMap":
        if not isinstance(data, dict):
            return cls([], [])
        edges = []
        for e in data.get("edges", []):
            if isinstance(e, dict):
                edges.append((e.get("from") or e.get("source"), e.get("to") or e.get("target")))
            elif isinstance(e, (list, tuple)) and len(e) == 2:
                edges.append((e[0], e[1]))
        nodes = list(data.get("nodes", []))
        nodes = [n["id"] if isinstance(n, dict) else n for n in nodes]
        for a, b in edges:
            nodes += [a, b]
        return cls([n for n in nodes if n], [(a, b) for a, b in edges if a and b])

    def dependencies(self, service: str) -> set[str]:
        seen: set[str] = set()
        stack = [service]
        while stack:
            for nxt in self.calls.get(stack.pop(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen


def rank_suspects(
    incident: dict[str, Any],
    service_map: ServiceMap,
    changes: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    window_s: float = 1800.0,
) -> list[dict[str, Any]]:
    start = to_epoch(incident.get("started_at")) or 0.0
    symptom = incident.get("service", "")
    scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}

    def add(svc: str, pts: float, why: str) -> None:
        scores[svc] = scores.get(svc, 0.0) + pts
        reasons.setdefault(svc, []).append(why)

    for ch in changes:
        ts = to_epoch(ch.get("ts"))
        if ts is None or not (start - window_s <= ts <= start + 60):
            continue
        add(ch["service"], 4, f"{ch.get('type')} change '{ch.get('message', '')}' {int(start - ts)}s before incident")
    first = first_error_by_service(clusters)
    sym_first = first.get(symptom)
    seen_services = set()
    for c in clusters:
        svc = c["service"]
        if svc not in seen_services:
            add(svc, 2, "warning/error logs")
            seen_services.add(svc)
        if has_latency_pattern(c["signature"]):
            add(svc, 2, "timeout/slow pattern in logs")
    for svc, ts in first.items():
        if svc != symptom and sym_first is not None and ts <= sym_first:
            add(svc, 3, "problems started before the symptom service")
    for svc in service_map.dependencies(symptom):
        add(svc, 1, f"upstream dependency of {symptom}")
    if symptom:
        add(symptom, 1, "service showing symptoms")
    ranked = sorted(scores, key=lambda s: (-scores[s], first.get(s, float("inf"))))
    return [{"service": s, "score": scores[s], "reasons": reasons[s]} for s in ranked]


def guess_category(suspect: str, symptom: str, clusters: list[dict], changes: list[dict]) -> str:
    text = " ".join(c["signature"].lower() for c in clusters if c["service"] == suspect)
    if any(k in text for k in ("pool", "exhaust", "memory", "oom", "disk")):
        return "resource"
    if suspect != symptom:
        return "cross_service"
    types = {c.get("type") for c in changes if c.get("service") == suspect}
    if "config" in types:
        return "config"
    return "code_bug"
