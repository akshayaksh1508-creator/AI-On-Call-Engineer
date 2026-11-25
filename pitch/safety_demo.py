"""Live Safety Demo Rehearsal Script (Day 10 Task B3).

Triggers all three core NightShift safety mechanisms live in sequence:
  1. T3 Escalation: T3 DB/infra action blocked from autonomous execution and routed
     to human approval (`GateDecision.HUMAN_APPROVAL_REQUIRED`).
  2. Auto-Rollback: Post-promotion metric degradation triggers `AutoRollbackGuard`
     and transitions the orchestrator to `IncidentState.ROLLEDBACK`.
  3. Kill Switch: Tripping `SafetyGate.trip_kill_switch()` immediately rejects
     even low-risk T1/T2 actions (`GateDecision.REJECTED`).

Owner: Person B (Brain & Trust)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

from contracts.models import Incident
from orchestrator.engine import OrchestratorEngine
from orchestrator.state_machine import IncidentState
from safety.gate import ActionRequest, GateDecision, RiskTier, SafetyGate

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_safety_demo_rehearsal(
    *,
    repo_root: Union[str, Path] = REPO_ROOT,
    out_path: Optional[Union[str, Path]] = REPO_ROOT / "results" / "safety_demo_rehearsal.json",
) -> Dict[str, Any]:
    """Trigger T3 escalation, auto-rollback, and kill switch live and return proof."""
    root = Path(repo_root).resolve()
    gate = SafetyGate()

    # 1. T3 Escalation
    t3_req = ActionRequest(
        incident_id="inc_safety_t3",
        action_type="patch",
        target_service="orders",
        risk_tier=RiskTier.T3,
        confidence=0.95,
        diff="-- DROP/ALTER DB schema migration",
        rationale="Create missing customer_id index on production orders DB",
    )
    t3_eval = gate.evaluate(t3_req)
    t3_ok = (
        t3_eval.decision == GateDecision.HUMAN_APPROVAL_REQUIRED
        and not t3_eval.allowed
        and t3_eval.requires_approval
    )

    # 2. Auto-Rollback via OrchestratorEngine on post-promotion degradation
    engine = OrchestratorEngine(repo_root=root)
    rb_incident = Incident(
        id="inc_safety_rollback",
        service="orders",
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        symptoms=["Post-promotion HTTP 5xx spike"],
        alerts=["OrdersCanaryRegression"],
    )
    rb_res = engine.handle_incident(
        rb_incident,
        fault_id="fault_001_bad_deploy",
        post_promotion_error_rate=0.35,
    )
    rollback_ok = (
        not rb_res.success
        and rb_res.final_state == IncidentState.ROLLEDBACK
        and rb_res.verification is not None
        and rb_res.verification.verdict == "ROLLBACK"
    )

    # 3. Global Kill Switch
    gate.trip_kill_switch(reason="Live safety demo rehearsal")
    ks_active = gate.is_kill_switch_active()
    t1_req = ActionRequest(
        incident_id="inc_safety_ks",
        action_type="rollback",
        target_service="orders",
        risk_tier=RiskTier.T1,
        confidence=0.99,
        diff="",
        rationale="Low-risk T1 rollback attempted while kill switch active",
    )
    ks_eval = gate.evaluate(t1_req)
    kill_switch_ok = (
        ks_active
        and ks_eval.decision == GateDecision.REJECTED
        and not ks_eval.allowed
    )
    gate.reset_kill_switch()

    summary = {
        "t3_escalation": {
            "triggered": t3_ok,
            "decision": t3_eval.decision.value,
            "requires_approval": t3_eval.requires_approval,
            "reason": t3_eval.reason,
        },
        "auto_rollback": {
            "triggered": rollback_ok,
            "final_state": rb_res.final_state.value,
            "verdict": rb_res.verification.verdict if rb_res.verification else None,
        },
        "kill_switch": {
            "triggered": kill_switch_ok,
            "kill_switch_active_during_check": ks_active,
            "decision": ks_eval.decision.value,
            "reason": ks_eval.reason,
        },
        "all_safety_features_verified": t3_ok and rollback_ok and kill_switch_ok,
    }

    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    return summary


if __name__ == "__main__":
    res = run_safety_demo_rehearsal()
    print(json.dumps(res, indent=2))
    raise SystemExit(0 if res["all_safety_features_verified"] else 1)
