"""Draft Failure-Analysis Table Generator (Day 8 Task B4).

Generates a Markdown failure-analysis table from triage/benchmark results where
every row names:
  - Incident (`incident_id` / `fault_id`)
  - Cause of failure
  - Proposed change

Owner: Person B (Brain & Trust)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union


def generate_failure_analysis_rows(triage_payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extract normalized failure-analysis rows from a triage JSON payload."""
    rows: List[Dict[str, str]] = []
    for item in triage_payload.get("failures", []):
        incident = f"{item.get('incident_id', 'unknown')} ({item.get('fault_id', 'unknown')})"
        cause = (item.get("cause") or "Unspecified failure cause").strip()
        proposed = (item.get("proposed_change") or "Investigate and add targeted fix").strip()
        rows.append({
            "incident": incident,
            "fault_id": str(item.get("fault_id", "unknown")),
            "label": str(item.get("label", "unknown")),
            "cause_of_failure": cause,
            "proposed_change": proposed,
        })
    return rows


def write_failure_analysis_table(
    triage_json_path: Union[str, Path],
    *,
    out_md_path: Union[str, Path],
) -> List[Dict[str, str]]:
    """Read triage JSON and write the draft failure-analysis Markdown table."""
    triage_data = json.loads(Path(triage_json_path).read_text(encoding="utf-8"))
    rows = generate_failure_analysis_rows(triage_data)

    lines = [
        "# NightShift Benchmark v1 — Draft Failure-Analysis Table",
        "",
        "| Incident | Label | Cause of Failure | Proposed Change |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for r in rows:
        lines.append(
            f"| `{r['incident']}` | `{r['label']}` | {r['cause_of_failure']} | {r['proposed_change']} |"
        )

    out = Path(out_md_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows
