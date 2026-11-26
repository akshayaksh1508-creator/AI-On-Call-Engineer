"""Offline Dashboard Replay Fallback (Day 11 Task A3).

Replays a locally recorded incident run start-to-finish through the Live Dashboard
(`DashboardState` / FastAPI `/api/events`) with zero external network, LLM, or
container dependencies.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from dashboard.app import DashboardEventIn, DashboardState

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDED_REPLAY = REPO_ROOT / "results" / "recorded_replay_fault_001.json"


def build_default_recorded_events(
    *,
    incident_id: str = "inc_offline_replay_001",
    fault_id: str = "fault_001_bad_deploy",
) -> List[Dict[str, Any]]:
    """Return a deterministic recorded sequence of dashboard events from start to finish."""
    return [
        {
            "incident_id": incident_id,
            "stage": "Detected",
            "message": f"[OFFLINE REPLAY] HTTP 5xx spike (22.0%) detected for {fault_id}",
            "metric_error_rate": 0.002,
            "timestamp": "2026-11-25T12:00:00Z",
        },
        {
            "incident_id": incident_id,
            "stage": "Investigating",
            "message": "Querying orders service error logs",
            "tool_name": "query_logs",
            "tool_args": {"service": "orders", "level": "ERROR"},
            "tool_output": "TypeError: 'NoneType' object is not subscriptable at orders/app.py:82",
            "evidence_id": "ev_replay_log_001",
            "raw_log": '2026-11-25T12:00:02Z ERROR [orders] File "target-app/services/orders/app.py", line 82: TypeError',
            "metric_error_rate": 0.22,
            "marker": "fault",
            "cost_usd": 0.005,
            "timestamp": "2026-11-25T12:00:02Z",
        },
        {
            "incident_id": incident_id,
            "stage": "Investigating",
            "message": "Inspecting culprit commit c0ffee14a via git_diff",
            "tool_name": "git_diff",
            "tool_args": {"commit": "c0ffee14a"},
            "tool_output": "- discount_code = None\n+ discount_code = discount['code']",
            "evidence_id": "ev_replay_commit_001",
            "raw_log": "commit c0ffee14a: + discount_code = discount['code']",
            "cost_usd": 0.010,
            "timestamp": "2026-11-25T12:00:04Z",
        },
        {
            "incident_id": incident_id,
            "stage": "Proposed",
            "message": "Generated T2 code patch & opened remediation PR #101",
            "tool_name": "propose_fix",
            "tool_args": {"type": "patch", "risk_tier": "T2", "target_service": "orders"},
            "tool_output": "PR #101 opened",
            "evidence_id": "ev_replay_pr_101",
            "raw_log": "GitHub PR #101: + discount_code = discount.get('code') if isinstance(discount, dict) else None",
            "cost_usd": 0.014,
            "timestamp": "2026-11-25T12:00:06Z",
        },
        {
            "incident_id": incident_id,
            "stage": "Verifying",
            "message": "Isolated worktree tests & canary traffic window passed",
            "metric_error_rate": 0.05,
            "marker": "fix",
            "timestamp": "2026-11-25T12:00:08Z",
        },
        {
            "incident_id": incident_id,
            "stage": "Resolved",
            "message": "Verified production recovery (22.0% -> 0.20%)",
            "metric_error_rate": 0.002,
            "verdict": "PASS",
            "cost_usd": 0.014,
            "timestamp": "2026-11-25T12:00:10Z",
        },
    ]


def save_recorded_replay(
    events: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    out_path: Union[str, Path] = DEFAULT_RECORDED_REPLAY,
) -> Path:
    """Persist recorded replay events to a local JSON bundle for offline fallback."""
    ev_list = list(events) if events is not None else build_default_recorded_events()
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"events": ev_list}, indent=2) + "\n", encoding="utf-8")
    return target


def replay_recorded_run(
    *,
    replay_path: Union[str, Path] = DEFAULT_RECORDED_REPLAY,
    state: Optional[DashboardState] = None,
    post_fn: Optional[Callable[[Dict[str, Any]], Any]] = None,
    step_delay_seconds: float = 0.0,
) -> Dict[str, Any]:
    """Replay a recorded run start-to-finish into DashboardState or an HTTP/TestClient endpoint."""
    path = Path(replay_path)
    if not path.exists():
        save_recorded_replay(out_path=path)

    data = json.loads(path.read_text(encoding="utf-8"))
    events: List[Dict[str, Any]] = data.get("events", [])

    target_state = state or DashboardState()
    stages_played: List[str] = []

    for ev in events:
        if post_fn is not None:
            post_fn(ev)
        else:
            target_state.push_event(DashboardEventIn(**ev))
        stages_played.append(ev["stage"])
        if step_delay_seconds > 0:
            time.sleep(step_delay_seconds)

    return {
        "events_replayed": len(events),
        "stages_played": stages_played,
        "started_at_stage": stages_played[0] if stages_played else None,
        "ended_at_stage": stages_played[-1] if stages_played else None,
        "final_verdict": target_state.verdict if post_fn is None else events[-1].get("verdict", "PASS"),
        "completed_start_to_finish": (
            len(stages_played) >= 2
            and stages_played[0] == "Detected"
            and stages_played[-1] == "Resolved"
        ),
    }
