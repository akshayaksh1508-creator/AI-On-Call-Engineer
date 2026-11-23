"""Group log lines into error signatures (Day 3, B1)."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Iterable

from agent.rca_time import to_epoch

_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_HEX = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")
_NUM = re.compile(r"(?<![A-Za-z_\d])\d+(?:\.\d+)?")
_REQ = re.compile(r"(request_id|trace_id|req)=\S+", re.I)

BAD_LEVELS = {"WARN", "WARNING", "ERROR", "CRITICAL", "FATAL"}
LATENCY_WORDS = ("timeout", "timed out", "slow", "latency", "exceeded", "deadline")


def normalize(message: str) -> str:
    s = str(message)
    s = _REQ.sub(r"\1=<id>", s)
    s = _UUID.sub("<uuid>", s)
    s = _IP.sub("<ip>", s)
    s = _HEX.sub("<hex>", s)
    s = _NUM.sub("<n>", s)
    return re.sub(r"\s+", " ", s).strip()


def entries_of(result: Any) -> list[dict[str, Any]]:
    """Accept a list or {'entries'|'logs'|'results': [...]}."""
    if isinstance(result, list):
        return [e for e in result if isinstance(e, dict)]
    if isinstance(result, dict):
        for key in ("entries", "logs", "results"):
            if isinstance(result.get(key), list):
                return [e for e in result[key] if isinstance(e, dict)]
    return []


def cluster_logs(entries: Iterable[dict[str, Any]], bad_only: bool = True) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for e in entries:
        level = str(e.get("level", "")).upper()
        if bad_only and level not in BAD_LEVELS:
            continue
        svc = str(e.get("service", "unknown"))
        sig = normalize(e.get("message", ""))
        ts = to_epoch(e.get("ts"))
        g = groups.setdefault(
            (svc, sig),
            {"service": svc, "signature": sig, "level": level, "count": 0,
             "first_ts": ts, "last_ts": ts, "sample": e.get("message", ""), "trace_ids": []},
        )
        g["count"] += 1
        if ts is not None:
            g["first_ts"] = ts if g["first_ts"] is None else min(g["first_ts"], ts)
            g["last_ts"] = ts if g["last_ts"] is None else max(g["last_ts"], ts)
        if e.get("trace_id") and len(g["trace_ids"]) < 3:
            g["trace_ids"].append(e["trace_id"])
    return sorted(groups.values(), key=lambda g: (-g["count"], g["first_ts"] or 0))


def first_error_by_service(clusters: Iterable[dict[str, Any]]) -> dict[str, float]:
    first: dict[str, float] = {}
    for c in clusters:
        if c["first_ts"] is None:
            continue
        first[c["service"]] = min(first.get(c["service"], c["first_ts"]), c["first_ts"])
    return first


def counts_by_service(clusters: Iterable[dict[str, Any]]) -> Counter:
    out: Counter = Counter()
    for c in clusters:
        out[c["service"]] += c["count"]
    return out


def has_latency_pattern(signature: str) -> bool:
    low = signature.lower()
    return any(w in low for w in LATENCY_WORDS)
