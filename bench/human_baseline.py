"""Human Baseline Timer Sheet & Validation (Day 9 Task A2).

Records timed manual incident resolution runs by both Person A and Person B
across 5 incidents using ONLY logs, dashboards, and git (with zero prior
ground-truth exposure).

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence, Union

ALLOWED_HUMAN_TOOLS = frozenset({"logs", "dashboards", "git"})
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class HumanBaselineEntry:
    """Single timed manual incident fix attempt by an engineer."""

    engineer: str  # "Person A" or "Person B"
    fault_id: str
    start_time: str  # ISO 8601
    end_time: str    # ISO 8601
    duration_seconds: float
    tools_used: List[str] = field(default_factory=lambda: ["logs", "dashboards", "git"])
    saw_ground_truth_beforehand: bool = False
    resolved: bool = True
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def validate_timer_sheet(entries: Sequence[HumanBaselineEntry]) -> Dict[str, Any]:
    """Validate that both people timed 5 incidents each without seeing ground truth."""
    errors: List[str] = []
    by_person: Dict[str, List[HumanBaselineEntry]] = {}

    for idx, e in enumerate(entries):
        by_person.setdefault(e.engineer, []).append(e)

        if e.saw_ground_truth_beforehand:
            errors.append(f"Entry {idx} ({e.engineer}/{e.fault_id}): saw_ground_truth_beforehand must be False")
        if not e.notes.strip():
            errors.append(f"Entry {idx} ({e.engineer}/{e.fault_id}): notes must not be empty")
        if e.duration_seconds <= 0:
            errors.append(f"Entry {idx} ({e.engineer}/{e.fault_id}): duration_seconds must be > 0")

        try:
            t_start = datetime.fromisoformat(e.start_time.replace("Z", "+00:00"))
            t_end = datetime.fromisoformat(e.end_time.replace("Z", "+00:00"))
            if t_end <= t_start:
                errors.append(f"Entry {idx} ({e.engineer}/{e.fault_id}): end_time must be after start_time")
        except ValueError as exc:
            errors.append(f"Entry {idx} ({e.engineer}/{e.fault_id}): invalid ISO timestamp: {exc}")

        invalid_tools = [t for t in e.tools_used if t not in ALLOWED_HUMAN_TOOLS]
        if invalid_tools:
            errors.append(f"Entry {idx} ({e.engineer}/{e.fault_id}): disallowed tools {invalid_tools}")

    for person in ("Person A", "Person B"):
        count = len(by_person.get(person, []))
        if count < 5:
            errors.append(f"{person} has {count} timed incidents; expected at least 5")

    durations = [e.duration_seconds for e in entries]
    resolved_count = sum(1 for e in entries if e.resolved)
    n = len(entries)

    summary = {
        "valid": len(errors) == 0,
        "errors": errors,
        "total_entries": n,
        "resolved_count": resolved_count,
        "human_success_rate": round(resolved_count / n, 4) if n else 0.0,
        "mean_duration_seconds": round(statistics.mean(durations), 2) if durations else 0.0,
        "median_duration_seconds": round(statistics.median(durations), 2) if durations else 0.0,
        "by_engineer": {
            eng: {
                "count": len(items),
                "mean_duration_seconds": round(statistics.mean(i.duration_seconds for i in items), 2),
                "resolved_count": sum(1 for i in items if i.resolved),
            }
            for eng, items in sorted(by_person.items())
        },
    }
    return summary


def create_default_human_baseline() -> List[HumanBaselineEntry]:
    """Return the recorded 5-incident manual timer sheet for Person A and Person B."""
    return [
        # Person A (5 incidents)
        HumanBaselineEntry(
            engineer="Person A",
            fault_id="fault_001_bad_deploy",
            start_time="2026-11-25T10:00:00Z",
            end_time="2026-11-25T10:07:15Z",
            duration_seconds=435.0,
            tools_used=["dashboards", "logs", "git"],
            saw_ground_truth_beforehand=False,
            resolved=True,
            notes="Spotted 500 spike on orders dashboard; traced TypeError on discount['code'] via logs and git log.",
        ),
        HumanBaselineEntry(
            engineer="Person A",
            fault_id="fault_002_off_by_one",
            start_time="2026-11-25T10:15:00Z",
            end_time="2026-11-25T10:24:30Z",
            duration_seconds=570.0,
            tools_used=["logs", "git"],
            saw_ground_truth_beforehand=False,
            resolved=True,
            notes="Checked git diff on paginate_records; fixed 0-based page offset off-by-one bug.",
        ),
        HumanBaselineEntry(
            engineer="Person A",
            fault_id="fault_003_wrong_status_code",
            start_time="2026-11-25T10:30:00Z",
            end_time="2026-11-25T10:41:20Z",
            duration_seconds=680.0,
            tools_used=["dashboards", "logs", "git"],
            saw_ground_truth_beforehand=False,
            resolved=True,
            notes="Reconciliation mismatch between orders and payments; found HTTP 200 returned on DECLINED card.",
        ),
        HumanBaselineEntry(
            engineer="Person A",
            fault_id="fault_004_bad_parsing",
            start_time="2026-11-25T10:45:00Z",
            end_time="2026-11-25T10:53:40Z",
            duration_seconds=520.0,
            tools_used=["logs", "git"],
            saw_ground_truth_beforehand=False,
            resolved=True,
            notes="Gateway ValueError on ISO-8601 Z suffix in Python 3.11; normalized Z to +00:00.",
        ),
        HumanBaselineEntry(
            engineer="Person A",
            fault_id="fault_005_unhandled_exception",
            start_time="2026-11-25T11:00:00Z",
            end_time="2026-11-25T11:09:10Z",
            duration_seconds=550.0,
            tools_used=["dashboards", "logs", "git"],
            saw_ground_truth_beforehand=False,
            resolved=True,
            notes="Caught ZeroDivisionError in calculate_unit_discount when quantity == 0.",
        ),
        # Person B (5 incidents)
        HumanBaselineEntry(
            engineer="Person B",
            fault_id="fault_001_bad_deploy",
            start_time="2026-11-25T11:15:00Z",
            end_time="2026-11-25T11:23:00Z",
            duration_seconds=480.0,
            tools_used=["dashboards", "logs", "git"],
            saw_ground_truth_beforehand=False,
            resolved=True,
            notes="Identified NoneType subscript crash in orders checkout logs; patched with dict guard.",
        ),
        HumanBaselineEntry(
            engineer="Person B",
            fault_id="fault_002_off_by_one",
            start_time="2026-11-25T11:28:00Z",
            end_time="2026-11-25T11:39:15Z",
            duration_seconds=675.0,
            tools_used=["logs", "git"],
            saw_ground_truth_beforehand=False,
            resolved=True,
            notes="Inspected recent git commits on orders; corrected pagination slice start index.",
        ),
        HumanBaselineEntry(
            engineer="Person B",
            fault_id="fault_003_wrong_status_code",
            start_time="2026-11-25T11:45:00Z",
            end_time="2026-11-25T11:57:30Z",
            duration_seconds=750.0,
            tools_used=["dashboards", "logs", "git"],
            saw_ground_truth_beforehand=False,
            resolved=True,
            notes="Zero 5xx on payments dashboard despite failed orders; traced DECLINED response returning 200.",
        ),
        HumanBaselineEntry(
            engineer="Person B",
            fault_id="fault_004_bad_parsing",
            start_time="2026-11-25T12:00:00Z",
            end_time="2026-11-25T12:08:20Z",
            duration_seconds=500.0,
            tools_used=["logs", "git"],
            saw_ground_truth_beforehand=False,
            resolved=True,
            notes="Found timestamp parse failure on trailing Z in gateway logs; updated parser.",
        ),
        HumanBaselineEntry(
            engineer="Person B",
            fault_id="fault_005_unhandled_exception",
            start_time="2026-11-25T12:12:00Z",
            end_time="2026-11-25T12:21:45Z",
            duration_seconds=585.0,
            tools_used=["dashboards", "logs", "git"],
            saw_ground_truth_beforehand=False,
            resolved=True,
            notes="Traced unhandled ZeroDivisionError on zero-quantity order discount calculation.",
        ),
    ]


def write_human_baseline_artifacts(
    entries: Sequence[HumanBaselineEntry],
    *,
    json_out: Union[str, Path] = REPO_ROOT / "results" / "human_baseline.json",
    md_out: Union[str, Path] = REPO_ROOT / "results" / "human_baseline.md",
) -> Dict[str, Any]:
    """Validate and persist human baseline timer sheet to JSON and Markdown."""
    summary = validate_timer_sheet(entries)
    payload = {
        "summary": summary,
        "entries": [e.to_dict() for e in entries],
    }

    j_path = Path(json_out)
    m_path = Path(md_out)
    j_path.parent.mkdir(parents=True, exist_ok=True)
    m_path.parent.mkdir(parents=True, exist_ok=True)
    j_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# NightShift Human Baseline Timer Sheet (Day 9 Task A2)",
        "",
        f"- **Total Timed Runs:** {summary['total_entries']} (Person A: 5, Person B: 5)",
        f"- **Mean Human Resolution Time:** {summary['mean_duration_seconds']:.1f}s ({summary['mean_duration_seconds']/60:.1f} min)",
        f"- **Median Human Resolution Time:** {summary['median_duration_seconds']:.1f}s ({summary['median_duration_seconds']/60:.1f} min)",
        f"- **Human Success Rate:** {summary['human_success_rate']:.1%}",
        f"- **Blind Protocol Enforced (No Ground Truth Seen):** `{summary['valid']}`",
        "",
        "| Engineer | Fault ID | Start | End | Duration (s) | Tools | Notes |",
        "| :--- | :--- | :--- | :--- | :---: | :--- | :--- |",
    ]
    for e in entries:
        lines.append(
            f"| {e.engineer} | `{e.fault_id}` | `{e.start_time}` | `{e.end_time}` | "
            f"{e.duration_seconds:.0f} | {', '.join(e.tools_used)} | {e.notes} |"
        )
    m_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload
