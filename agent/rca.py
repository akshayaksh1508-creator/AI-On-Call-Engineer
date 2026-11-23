"""Root-cause investigator (Day 3, B1/B3/B4).

    from agent.rca import investigate, AnthropicLLM
    out = investigate(incident, client, llm=AnthropicLLM())      # LLM + tools
    out = investigate(incident, client)                           # free heuristic baseline

`client` is your PlatformClient (live or FixtureClient). It must expose methods named
like the tools: query_logs, query_metrics, list_changes, git_log, git_diff, read_file,
service_map, search_past_incidents (missing ones are reported to the model as unavailable).

If your Day 2 loop already exists you can keep it and only reuse rca_strategy.py,
log_clustering.py and rca_evaluator.py. This file is self-contained so it also works alone.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from agent.log_clustering import cluster_logs, entries_of
from agent.rca_strategy import CATEGORIES, PROMPTS, ServiceMap, guess_category, rank_suspects
from agent.rca_time import to_epoch

# ---------------------------------------------------------------- evidence


@dataclass
class Evidence:
    id: str
    type: str  # log | metric | commit | config | deploy | service_map | file | past_incident
    ref: str
    excerpt: str
    ts: float | None = None


class EvidenceStore:
    def __init__(self) -> None:
        self.items: list[Evidence] = []

    def add(self, type: str, ref: str, excerpt: str, ts: float | None = None) -> str:
        eid = f"E{len(self.items) + 1}"
        self.items.append(Evidence(eid, type, ref, str(excerpt)[:400], ts))
        return eid

    def ids(self) -> set[str]:
        return {e.id for e in self.items}

    def to_list(self) -> list[dict[str, Any]]:
        return [e.__dict__ for e in self.items]


# ---------------------------------------------------------------- tools

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {"name": "query_logs", "description": "Search logs. Returns entries and an evidence id.",
     "input_schema": {"type": "object", "properties": {
         "service": {"type": "string"}, "level": {"type": "string"}, "since": {"type": "number", "description": "epoch seconds"},
         "until": {"type": "number"}, "text": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "query_metrics", "description": "Query a metric (error rate, latency) over a time range.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string"}, "start": {"type": "number"}, "end": {"type": "number"}}, "required": ["query"]}},
    {"name": "list_changes", "description": "List deploys and config changes in a time range.",
     "input_schema": {"type": "object", "properties": {
         "since": {"type": "number"}, "until": {"type": "number"}, "service": {"type": "string"}}}},
    {"name": "git_log", "description": "Recent commits, optionally for a path.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "since": {"type": "number"}, "until": {"type": "number"}, "n": {"type": "integer"}}}},
    {"name": "git_diff", "description": "Diff of a commit (or base..head).",
     "input_schema": {"type": "object", "properties": {
         "commit": {"type": "string"}, "base": {"type": "string"}, "head": {"type": "string"}, "path": {"type": "string"}}}},
    {"name": "read_file", "description": "Read a source file (optionally at a commit).",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "ref": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}},
         "required": ["path"]}},
    {"name": "service_map", "description": "Service dependency graph (A calls B).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "search_past_incidents", "description": "Similar past incidents (may be empty).",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}}},
]

SUBMIT_SCHEMA: dict[str, Any] = {
    "name": "submit_hypotheses",
    "description": "Submit final ranked hypotheses (max 3). Ends the investigation.",
    "input_schema": {"type": "object", "properties": {"hypotheses": {"type": "array", "maxItems": 3, "items": {
        "type": "object", "properties": {
            "cause": {"type": "string"},
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "culprit_service": {"type": "string"},
            "culprit_change": {"type": "string", "description": "change id or commit sha, if any"},
            "confidence": {"type": "number"},
            "evidence_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["cause", "category", "culprit_service", "confidence", "evidence_ids"]}}},
        "required": ["hypotheses"]},
}


class ToolRouter:
    def __init__(self, client: Any, store: EvidenceStore, max_chars: int = 6000):
        self.client, self.store, self.max_chars = client, store, max_chars
        self.calls: list[dict[str, Any]] = []

    def call(self, name: str, args: dict[str, Any], phase: str = "llm") -> dict[str, Any]:
        t0 = time.time()
        fn = getattr(self.client, name, None)
        error = None
        if fn is None:
            if name == "search_past_incidents":
                result: Any = {"results": []}
            else:
                result, error = {"error": f"tool {name} unavailable"}, "unavailable"
        else:
            try:
                result = fn(**args)
            except Exception as exc:  # tool failure is data for the model, not a crash
                error = f"{type(exc).__name__}: {exc}"
                result = {"error": error}
        self.calls.append({"tool": name, "args": args, "phase": phase,
                           "seconds": round(time.time() - t0, 3), "error": error})
        return self._wrap(name, args, result)

    def _wrap(self, name: str, args: dict, result: Any) -> dict[str, Any]:
        if isinstance(result, dict) and "error" in result and len(result) == 1:
            return result
        if name == "list_changes":
            items = result.get("changes", result) if isinstance(result, dict) else result
            items = [dict(c) for c in items if isinstance(c, dict)]
            for c in items:
                c["evidence_id"] = self.store.add(
                    "config" if c.get("type") == "config" else "deploy",
                    c.get("id", "change"), f"{c.get('type')} {c.get('service')}: {c.get('message')} meta={c.get('meta')}",
                    to_epoch(c.get("ts")))
            return self._fit({"changes": items})
        if name == "query_logs":
            items = entries_of(result)
            eid = self.store.add("log", f"logs:{args}", "; ".join(
                f"{e.get('service')} {e.get('level')} {e.get('message')}" for e in items[:3]))
            return self._fit({"evidence_id": eid, "entries": items})
        kind = {"git_diff": "commit", "git_log": "commit", "read_file": "file", "service_map": "service_map",
                "query_metrics": "metric", "search_past_incidents": "past_incident"}.get(name, "log")
        eid = self.store.add(kind, f"{name}:{args}", json.dumps(result, default=str)[:300])
        return self._fit({"evidence_id": eid, "result": result})

    def _fit(self, obj: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(obj, default=str)) <= self.max_chars:
            return obj
        for key, val in list(obj.items()):
            if isinstance(val, list):
                while val and len(json.dumps(obj, default=str)) > self.max_chars:
                    val = val[: max(1, len(val) // 2)] if len(val) > 1 else []
                    obj[key] = val
                obj["truncated"] = True
        if len(json.dumps(obj, default=str)) > self.max_chars:
            return {"evidence_id": obj.get("evidence_id"), "truncated_text": json.dumps(obj, default=str)[: self.max_chars]}
        return obj


# ---------------------------------------------------------------- LLM adapters


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMReply:
    content: list[dict[str, Any]]
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def tool_calls(self) -> list[ToolCall]:
        return [ToolCall(b["id"], b["name"], b.get("input", {})) for b in self.content if b.get("type") == "tool_use"]


class LLM(Protocol):
    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMReply: ...


class AnthropicLLM:
    """Needs `pip install anthropic` and ANTHROPIC_API_KEY. Model via ANTHROPIC_MODEL."""

    def __init__(self, model: str | None = None, max_tokens: int = 2000):
        import anthropic  # imported lazily so tests run without it

        self.client = anthropic.Anthropic()
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        self.max_tokens = max_tokens

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
        resp = self.client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=system, messages=messages, tools=tools
        )
        blocks: list[dict[str, Any]] = []
        for b in resp.content:
            if b.type == "text":
                blocks.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        return LLMReply(blocks, {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens})


class ScriptedLLM:
    """Test double: each script item is a list of content blocks (or a callable(messages) -> blocks)."""

    def __init__(self, script: list[Any]):
        self.script, self.i, self.seen_tools = list(script), 0, []

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMReply:
        self.seen_tools.append([t["name"] for t in tools])
        item = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        blocks = item(messages) if callable(item) else item
        return LLMReply(blocks, {"input_tokens": 100, "output_tokens": 50})


def estimate_cost(usage: dict[str, int]) -> float:
    """USD estimate. Adjust prices (per million tokens) to current pricing via env vars."""
    pin = float(os.getenv("PRICE_IN_PER_M", "3.0"))
    pout = float(os.getenv("PRICE_OUT_PER_M", "15.0"))
    return round(usage.get("input_tokens", 0) / 1e6 * pin + usage.get("output_tokens", 0) / 1e6 * pout, 5)


# ---------------------------------------------------------------- core logic


def prefetch(incident: dict[str, Any], router: ToolRouter, window_s: float = 1800.0) -> dict[str, Any]:
    """Mandatory first steps: changes, service map, error clusters. Guaranteed by code."""
    start = to_epoch(incident.get("started_at")) or time.time()
    changes_res = router.call("list_changes", {"since": start - window_s, "until": start + 120}, "prefetch")
    changes = changes_res.get("changes", []) if isinstance(changes_res, dict) else []
    smap_res = router.call("service_map", {}, "prefetch")
    smap_raw = smap_res.get("result", smap_res) if isinstance(smap_res, dict) else {}
    smap = ServiceMap.from_dict(smap_raw)
    logs_res = router.call("query_logs", {"since": start - 300, "until": start + 600, "limit": 500}, "prefetch")
    clusters = cluster_logs(logs_res.get("entries", []) if isinstance(logs_res, dict) else [])
    for c in clusters[:8]:
        c["evidence_id"] = router.store.add(
            "log", f"cluster:{c['service']}", f"{c['service']} x{c['count']}: {c['sample']}", c["first_ts"])
    suspects = rank_suspects(incident, smap, changes, clusters, window_s)
    return {"changes": changes, "service_map": smap, "clusters": clusters, "suspects": suspects}


def heuristic_hypotheses(incident: dict, ctx: dict, store: EvidenceStore) -> list[dict[str, Any]]:
    out = []
    for s in ctx["suspects"][:3]:
        svc = s["service"]
        cl = [c for c in ctx["clusters"] if c["service"] == svc]
        ch = [c for c in ctx["changes"] if c.get("service") == svc]
        ev = [c["evidence_id"] for c in ch if c.get("evidence_id")] + [c["evidence_id"] for c in cl[:2] if c.get("evidence_id")]
        top = cl[0]["sample"] if cl else "no error logs"
        cause = f"{svc}: " + "; ".join(s["reasons"][:3]) + f". Top log: {top}"
        out.append({
            "cause": cause, "category": guess_category(svc, incident.get("service", ""), ctx["clusters"], ctx["changes"]),
            "culprit_service": svc, "culprit_change": (ch[0].get("id") if ch else ""),
            "confidence": round(min(0.75, 0.15 + s["score"] / 20), 2), "evidence_ids": ev,
        })
    return out


def validate_hypotheses(raw: list[dict[str, Any]], store: EvidenceStore) -> list[dict[str, Any]]:
    known = store.ids()
    out = []
    for h in raw or []:
        if not isinstance(h, dict) or not h.get("cause"):
            continue
        conf = max(0.0, min(1.0, float(h.get("confidence", 0) or 0)))
        ids = [str(i) for i in h.get("evidence_ids", [])]
        valid = [i for i in ids if i in known]
        flags = []
        if len(valid) != len(ids):
            flags.append("unknown_evidence_ids")
            conf *= 0.5
        if not valid:
            flags.append("guess")
            conf = min(conf, 0.3)
        cat = h.get("category") if h.get("category") in CATEGORIES else "unknown"
        out.append({"cause": h["cause"], "category": cat, "culprit_service": h.get("culprit_service", ""),
                    "culprit_change": h.get("culprit_change", ""), "confidence": round(conf, 3),
                    "evidence_ids": valid, "flags": flags})
    out.sort(key=lambda x: -x["confidence"])
    return out[:3]


def _initial_message(incident: dict, ctx: dict) -> str:
    sus = [{"service": s["service"], "score": s["score"], "reasons": s["reasons"]} for s in ctx["suspects"][:4]]
    ch = [{k: c.get(k) for k in ("evidence_id", "id", "type", "service", "message", "ts", "meta")} for c in ctx["changes"]]
    cl = [{k: c.get(k) for k in ("evidence_id", "service", "count", "level", "sample", "first_ts")} for c in ctx["clusters"][:8]]
    return ("INCIDENT:\n" + json.dumps(incident, default=str) + "\n\nRECENT CHANGES (already fetched):\n" + json.dumps(ch, default=str)
            + "\n\nERROR/WARN CLUSTERS:\n" + json.dumps(cl, default=str)
            + "\n\nSUSPECT RANKING (hint, verify it):\n" + json.dumps(sus, default=str)
            + "\n\nInvestigate further if needed, then call submit_hypotheses.")


def _llm_loop(incident, ctx, router, llm, system, max_steps) -> tuple[list[dict] | None, dict[str, int], int]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": _initial_message(incident, ctx)}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    steps, nudged, budget_hit = 0, False, False
    while True:
        tools = [SUBMIT_SCHEMA] if budget_hit else TOOL_SCHEMAS + [SUBMIT_SCHEMA]
        reply = llm.complete(system, messages, tools)
        for k in usage:
            usage[k] += reply.usage.get(k, 0)
        messages.append({"role": "assistant", "content": reply.content})
        calls = reply.tool_calls
        for tc in calls:
            if tc.name == "submit_hypotheses":
                return tc.input.get("hypotheses", []), usage, steps
        if not calls:
            if nudged or budget_hit:
                return None, usage, steps
            nudged = True
            messages.append({"role": "user", "content": "Call submit_hypotheses now with your best ranked hypotheses."})
            continue
        if budget_hit:
            return None, usage, steps  # model ignored the forced submit
        results = []
        for tc in calls:
            steps += 1
            res = router.call(tc.name, tc.input) if steps <= max_steps else {"error": "step budget exhausted"}
            results.append({"type": "tool_result", "tool_use_id": tc.id, "content": json.dumps(res, default=str)})
        if steps >= max_steps:
            budget_hit = True
            results.append({"type": "text", "text": "Step budget exhausted. Call submit_hypotheses now."})
        messages.append({"role": "user", "content": results})


def investigate(
    incident: dict[str, Any],
    client: Any,
    llm: LLM | None = None,
    prompt_version: str = "v3",
    max_steps: int = 15,
    use_prefetch: bool = True,
    window_s: float = 1800.0,
) -> dict[str, Any]:
    t0 = time.time()
    store = EvidenceStore()
    router = ToolRouter(client, store)
    ctx = prefetch(incident, router, window_s) if use_prefetch else {
        "changes": [], "service_map": ServiceMap([], []), "clusters": [], "suspects": []}
    raw, usage, steps, fallback = None, {"input_tokens": 0, "output_tokens": 0}, 0, False
    if llm is not None:
        raw, usage, steps = _llm_loop(incident, ctx, router, llm, PROMPTS[prompt_version], max_steps)
    hyps = validate_hypotheses(raw or [], store)
    if not hyps:
        fallback = True
        hyps = validate_hypotheses(heuristic_hypotheses(incident, ctx, store), store)
    return {
        "incident_id": incident.get("id"), "prompt_version": prompt_version if llm else "heuristic",
        "hypotheses": hyps, "evidence": store.to_list(), "tool_calls": router.calls, "llm_steps": steps,
        "usage": usage, "cost_usd": estimate_cost(usage), "fallback_used": fallback,
        "suspects": [{"service": s["service"], "score": s["score"]} for s in ctx["suspects"][:4]],
        "seconds": round(time.time() - t0, 3),
    }
