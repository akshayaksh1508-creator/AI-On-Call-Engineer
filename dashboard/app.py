"""NightShift Live Incident Dashboard & Trace Viewer (Day 9 Tasks B1 & B2).

Provides:
  - 1080p projector-readable dark-mode UI (`GET /`)
  - Live event ingestion & streaming (`POST /api/events`, `GET /api/state`, `GET /api/events`)
  - Incident timeline, collapsible agent trace tool calls, clickable evidence IDs
    resolving to raw log lines or git commits (`GET /api/evidence/{evidence_id}`)
  - Metric graph with fault injection and fix markers, verdict, and cost
  - 5-chart benchmark results view (`GET /results`)

Owner: Person B (Brain & Trust)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent


class DashboardEventIn(BaseModel):
    """Live event payload pushed by orchestrator/agent/verifier."""

    stage: str
    message: str
    incident_id: str = "inc_live_001"
    timestamp: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_output: Optional[str] = None
    evidence_id: Optional[str] = None
    raw_log: Optional[str] = None
    metric_error_rate: Optional[float] = None
    marker: Optional[str] = None  # "fault" | "fix" | None
    verdict: Optional[str] = None
    cost_usd: Optional[float] = None


@dataclass
class DashboardState:
    """In-memory live state store for sub-2s dashboard updates."""

    incident_id: str = "inc_live_001"
    service: str = "orders"
    verdict: str = "IN_PROGRESS"
    cost_usd: float = 0.0
    timeline: List[Dict[str, Any]] = field(default_factory=list)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    evidence_store: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    metric_series: List[Dict[str, Any]] = field(default_factory=list)

    def push_event(self, ev: DashboardEventIn) -> Dict[str, Any]:
        ts = ev.timestamp or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.incident_id = ev.incident_id

        timeline_item = {
            "timestamp": ts,
            "stage": ev.stage,
            "message": ev.message,
            "evidence_id": ev.evidence_id,
            "received_at": time.time(),
        }
        self.timeline.append(timeline_item)

        if ev.evidence_id:
            self.evidence_store[ev.evidence_id] = {
                "evidence_id": ev.evidence_id,
                "raw_log": ev.raw_log or ev.tool_output or ev.message,
                "stage": ev.stage,
                "timestamp": ts,
            }

        if ev.tool_name:
            self.trace.append({
                "step": len(self.trace) + 1,
                "tool_name": ev.tool_name,
                "tool_args": ev.tool_args or {},
                "tool_output": ev.tool_output or "",
                "evidence_id": ev.evidence_id,
                "timestamp": ts,
            })

        if ev.metric_error_rate is not None:
            self.metric_series.append({
                "timestamp": ts,
                "error_rate": float(ev.metric_error_rate),
                "marker": ev.marker,
            })

        if ev.verdict:
            self.verdict = ev.verdict
        if ev.cost_usd is not None:
            self.cost_usd = float(ev.cost_usd)

        return timeline_item

    def to_dict(self) -> Dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "service": self.service,
            "verdict": self.verdict,
            "cost_usd": round(self.cost_usd, 6),
            "timeline": self.timeline,
            "trace": self.trace,
            "evidence_ids": list(self.evidence_store.keys()),
            "metric_series": self.metric_series,
        }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>NightShift Live SRE Console (1080p)</title>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --blue: #58a6ff;
    --green: #3fb950; --red: #f85149; --yellow: #d29922;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px; background: var(--bg); color: var(--text);
    font-family: "Segoe UI", Arial, sans-serif; font-size: 16px; line-height: 1.5;
  }
  header {
    display: flex; justify-content: space-between; align-items: center;
    padding-bottom: 16px; border-bottom: 2px solid var(--border); margin-bottom: 20px;
  }
  h1 { margin: 0; font-size: 28px; color: var(--blue); }
  .badges { display: flex; gap: 16px; align-items: center; font-size: 18px; }
  .badge {
    padding: 8px 16px; border-radius: 8px; background: var(--panel);
    border: 1px solid var(--border); font-weight: 700;
  }
  .badge-pass { color: var(--green); border-color: var(--green); }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .panel {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px;
  }
  .panel h2 { margin-top: 0; font-size: 22px; color: var(--blue); }
  .timeline-item { padding: 8px 0; border-bottom: 1px solid #21262d; }
  details.tool-call {
    background: #0d1117; border: 1px solid var(--border);
    border-radius: 6px; padding: 10px 14px; margin-bottom: 10px;
  }
  details.tool-call summary { cursor: pointer; font-weight: 600; font-size: 16px; }
  .evidence-btn {
    background: #1f6feb; color: #fff; border: none; border-radius: 4px;
    padding: 4px 10px; cursor: pointer; font-family: Consolas, monospace; font-size: 14px;
  }
  .evidence-btn:hover { background: #388bfd; }
  pre.raw-log {
    background: #010409; color: #79c0ff; padding: 14px; border-radius: 6px;
    border: 1px solid var(--border); overflow-x: auto; font-size: 14px;
  }
</style>
</head>
<body>
<header>
  <h1>NightShift Autonomous SRE — Live Console</h1>
  <div class="badges">
    <span class="badge" id="inc-badge">Incident: --</span>
    <span class="badge badge-pass" id="verdict-badge">Verdict: IN_PROGRESS</span>
    <span class="badge" id="cost-badge">Cost: $0.0000</span>
    <a href="/results" style="color:#58a6ff;font-weight:600;">View 5 Charts &rarr;</a>
  </div>
</header>
<div class="grid">
  <section class="panel">
    <h2>1. Incident Timeline</h2>
    <div id="timeline-list"></div>
  </section>
  <section class="panel">
    <h2>2. Metric Graph (Fault &amp; Fix Markers)</h2>
    <svg id="metric-svg" width="100%" height="240" viewBox="0 0 700 240"></svg>
  </section>
  <section class="panel">
    <h2>3. Agent Trace (Collapsible Tool Calls)</h2>
    <div id="trace-list"></div>
  </section>
  <section class="panel">
    <h2>4. Evidence Inspector (Click Evidence ID)</h2>
    <div id="evidence-buttons" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;"></div>
    <pre class="raw-log" id="evidence-raw">Click an evidence ID to view exact raw log line or git commit...</pre>
  </section>
</div>
<script>
async function openEvidence(evId) {
  const resp = await fetch(`/api/evidence/${encodeURIComponent(evId)}`);
  if (resp.ok) {
    const data = await resp.json();
    document.getElementById("evidence-raw").textContent =
      `[${data.evidence_id}] (${data.stage} @ ${data.timestamp})\n${data.raw_log}`;
  }
}
function renderGraph(series) {
  const svg = document.getElementById("metric-svg");
  if (!series.length) { svg.innerHTML = ""; return; }
  const w = 700, h = 240, pad = 40;
  const maxR = Math.max(0.25, ...series.map(p => p.error_rate)) * 1.1;
  const pts = series.map((p, i) => {
    const x = pad + (series.length === 1 ? 0 : (i / (series.length - 1)) * (w - 2 * pad));
    const y = h - pad - (p.error_rate / maxR) * (h - 2 * pad);
    return {x, y, ...p};
  });
  let html = `<polyline fill="none" stroke="#58a6ff" stroke-width="3" points="${pts.map(p=>`${p.x},${p.y}`).join(" ")}"/>`;
  for (const p of pts) {
    if (p.marker === "fault") {
      html += `<circle cx="${p.x}" cy="${p.y}" r="6" fill="#f85149"/><text x="${p.x}" y="${p.y-10}" fill="#f85149" font-size="13">FAULT</text>`;
    } else if (p.marker === "fix") {
      html += `<circle cx="${p.x}" cy="${p.y}" r="6" fill="#3fb950"/><text x="${p.x}" y="${p.y-10}" fill="#3fb950" font-size="13">FIX</text>`;
    }
  }
  svg.innerHTML = html;
}
async function refreshState() {
  const resp = await fetch("/api/state");
  const st = await resp.json();
  document.getElementById("inc-badge").textContent = `Incident: ${st.incident_id}`;
  document.getElementById("verdict-badge").textContent = `Verdict: ${st.verdict}`;
  document.getElementById("cost-badge").textContent = `Cost: $${st.cost_usd.toFixed(4)}`;
  document.getElementById("timeline-list").innerHTML = st.timeline.map(t =>
    `<div class="timeline-item"><strong>[${t.stage}]</strong> ${t.message} ${t.evidence_id ? `<button class="evidence-btn" onclick="openEvidence('${t.evidence_id}')">${t.evidence_id}</button>` : ""}</div>`
  ).join("");
  document.getElementById("trace-list").innerHTML = st.trace.map(tr =>
    `<details class="tool-call"><summary>Step ${tr.step}: ${tr.tool_name}</summary><pre class="raw-log">${JSON.stringify(tr.tool_args)}\nOutput: ${tr.tool_output}</pre>${tr.evidence_id ? `<button class="evidence-btn" onclick="openEvidence('${tr.evidence_id}')">${tr.evidence_id}</button>` : ""}</details>`
  ).join("");
  document.getElementById("evidence-buttons").innerHTML = st.evidence_ids.map(eid =>
    `<button class="evidence-btn" data-evidence-id="${eid}" onclick="openEvidence('${eid}')">${eid}</button>`
  ).join("");
  renderGraph(st.metric_series);
}
refreshState();
setInterval(refreshState, 500);
</script>
</body>
</html>
"""


def create_dashboard_app(
    *,
    state: Optional[DashboardState] = None,
    results_dir: Union[str, Path] = REPO_ROOT / "results",
) -> FastAPI:
    """Create FastAPI app for the Live Dashboard & Clickable Trace Viewer."""
    app = FastAPI(title="NightShift Live SRE Dashboard")
    store = state or DashboardState()
    res_root = Path(results_dir)

    @app.get("/", response_class=HTMLResponse)
    def dashboard_home() -> HTMLResponse:
        return HTMLResponse(DASHBOARD_HTML)

    @app.get("/results", response_class=HTMLResponse)
    def results_page() -> HTMLResponse:
        page = res_root / "results_page.html"
        if page.exists():
            return HTMLResponse(page.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Results page not generated yet</h1>", status_code=404)

    @app.post("/api/events")
    def post_event(event: DashboardEventIn) -> Dict[str, Any]:
        item = store.push_event(event)
        return {"ok": True, "event": item}

    @app.get("/api/state")
    def get_state() -> Dict[str, Any]:
        return store.to_dict()

    @app.get("/api/evidence/{evidence_id}")
    def get_evidence(evidence_id: str) -> Dict[str, Any]:
        if evidence_id not in store.evidence_store:
            raise HTTPException(status_code=404, detail=f"Evidence {evidence_id} not found")
        return store.evidence_store[evidence_id]

    return app
