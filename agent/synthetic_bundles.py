"""Synthetic incident bundles for faults 6-10, so B can iterate before live bundles are recorded.

IMPORTANT: these are hand-designed. Accuracy on them is a smoke test, NOT your benchmark number.
Record real bundles from the live system for the numbers you report.
"""
from __future__ import annotations

from typing import Any

T0 = 1_700_000_000.0
SERVICES = ["gateway", "orders", "payments"]
SERVICE_MAP = {"nodes": SERVICES, "edges": [{"from": "gateway", "to": "orders"}, {"from": "orders", "to": "payments"}]}

# (service, level, message template, start offset s, count). {n}/{id} are varied per line.
SCENARIOS: dict[str, dict[str, Any]] = {
    "fault_06": dict(symptom="gateway", change=("payments", "config", "Tune payments DB query settings", -20),
        logs=[("payments", "WARNING", "Slow query on payments_ledger took {n}ms request_id={id}", 0, 40),
              ("gateway", "ERROR", "Upstream timeout calling payments after 2000ms request_id={id}", 6, 60)]),
    "fault_07": dict(symptom="orders", change=("payments", "config", "Enable payments response schema v2", -25),
        logs=[("orders", "ERROR", "KeyError: 'amount' while parsing payments response request_id={id}", 0, 50),
              ("gateway", "ERROR", "orders returned 500 for request_id={id}", 4, 50)]),
    "fault_08": dict(symptom="orders", change=("orders", "config", "Enable new discount engine", -15),
        logs=[("orders", "ERROR", "AttributeError: 'NoneType' object has no attribute 'percent' in apply_discount request_id={id}", 0, 45),
              ("gateway", "ERROR", "orders returned 500 for request_id={id}", 3, 40)]),
    "fault_09": dict(symptom="gateway", change=("gateway", "config", "Adjust gateway upstream timeout", -30),
        logs=[("gateway", "ERROR", "Upstream timeout calling orders after 50ms request_id={id}", 0, 70)]),
    "fault_10": dict(symptom="orders", change=("orders", "config", "Resize orders database pool", -40),
        logs=[("orders", "ERROR", "QueuePool limit of size 1 overflow 0 reached, connection timed out, timeout 30.00", 0, 55),
              ("gateway", "ERROR", "orders returned 500 for request_id={id}", 8, 35)]),
}


def build_bundle(fault_id: str) -> dict[str, Any]:
    sc = SCENARIOS[fault_id]
    logs: list[dict[str, Any]] = []
    for k in range(120):  # healthy background noise before the incident
        logs.append({"ts": T0 - 600 + k * 4.5, "service": SERVICES[k % 3], "level": "INFO",
                     "message": f"GET /health 200 in {3 + k % 5}ms", "trace_id": f"{k:08x}"})
    for svc, level, tmpl, off, count in sc["logs"]:
        for k in range(count):
            logs.append({"ts": T0 + off + k * 1.5, "service": svc, "level": level,
                         "message": tmpl.format(n=2900 + k * 7, id=f"{(k * 2654435761) % (16 ** 10):010x}"),
                         "trace_id": f"{(k * 40503) % (16 ** 8):08x}"})
    logs.sort(key=lambda e: e["ts"])
    csvc, ctype, cmsg, coff = sc["change"]
    changes = [
        {"id": "chg-old0000001", "ts": T0 - 7200, "type": "deploy", "service": "gateway", "message": "Bump logging library", "meta": {}},
        {"id": f"chg-{fault_id}", "ts": T0 + coff, "type": ctype, "service": csvc, "message": cmsg, "meta": {"env": {"changed": True}}},
    ]
    first_symptom = min(off for svc, _, _, off, _ in sc["logs"] if svc == sc["symptom"])
    return {
        "fault_id": fault_id,
        "incident": {"id": f"inc-{fault_id}", "service": sc["symptom"], "started_at": T0 + first_symptom,
                     "symptoms": [], "alerts": [], "recent_changes": []},
        "logs": logs, "changes": changes, "service_map": SERVICE_MAP, "git_log": [], "diffs": {}, "files": {},
    }


def all_bundles() -> dict[str, dict[str, Any]]:
    return {fid: build_bundle(fid) for fid in SCENARIOS}
