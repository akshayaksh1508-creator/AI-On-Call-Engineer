"""Failure Triage Sheet Generator & Validator (Day 8 Task A2).

Labels every failed benchmark run as one of:
  - `detect`
  - `RCA`
  - `fix`
  - `verify`
  - `infrastructure`

Assigns a concise one-line cause to each failure and validates that
counts per label sum strictly to total failures.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Union

TriageLabel = Literal["detect", "RCA", "fix", "verify", "infrastructure"]
VALID_TRIAGE_LABELS: tuple[str, ...] = ("detect", "RCA", "fix", "verify", "infrastructure")


@dataclass
class TriagedFailure:
    """Single triaged failure entry."""

    fault_id: str
    incident_id: str
    label: TriageLabel
    cause: str
    proposed_change: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_failure_label(entry: Dict[str, Any]) -> tuple[TriageLabel, str, str]:
    """Infer the exact triage label, one-line cause, and proposed fix from a failed run entry."""
    status = entry.get("status", "fail")
    reason = (entry.get("classification_reason") or "").strip()
    rec = entry.get("run_record") or {}
    fault_id = entry.get("fault_id", "unknown")

    if status == "infra_error":
        cause = reason or f"Infrastructure service disruption during {fault_id}"
        return "infrastructure", cause.splitlines()[0][:180], "Harden reset retry, detector jitter tolerance, and canary min-sample guard"

    lower = reason.lower()
    if lower.startswith("detect:") or "detector" in lower or float(rec.get("t_detect", 1.0)) <= 0.0:
        cause = reason or f"Detector missed or timed out on {fault_id}"
        return "detect", cause.splitlines()[0][:180], "Tune detector anomaly threshold and sustained window"

    if lower.startswith("rca:") or (not rec.get("rca_correct_top3", True)):
        cause = reason or f"RCA hypothesis missed ground truth for {fault_id}"
        return "RCA", cause.splitlines()[0][:180], "Enrich RCA prompt and platform log/metric evidence"

    if lower.startswith("fix:") or (rec.get("rca_correct_top1", False) and "config" in lower):
        cause = reason or f"Fixer failed to generate valid patch/config revert for {fault_id}"
        return "fix", cause.splitlines()[0][:180], "Add missing config/patch template for fault category"

    if lower.startswith("verify:") or "sandbox" in lower or "canary" in lower or "recovery" in lower:
        cause = reason or f"Verification stage failed for {fault_id}"
        return "verify", cause.splitlines()[0][:180], "Implement sandbox reproducer and recovery metric check"

    if not rec.get("rca_correct_top1", True):
        cause = reason or f"Top-1 RCA missed root cause for {fault_id}"
        return "RCA", cause.splitlines()[0][:180], "Improve top-1 RCA ranking and evidence weighting"

    cause = reason or f"Remediation failed verification for {fault_id}"
    return "fix", cause.splitlines()[0][:180], "Refine fixer diff generation and validation"


def build_triage_sheet(results_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build and validate a complete failure triage sheet from a benchmark results payload."""
    runs: Sequence[Dict[str, Any]] = results_payload.get("runs", [])
    triaged: List[TriagedFailure] = []
    counts: Dict[str, int] = {lbl: 0 for lbl in VALID_TRIAGE_LABELS}

    for entry in runs:
        status = entry.get("status", "fail")
        rec = entry.get("run_record") or {}
        is_failure = status != "pass" or not bool(rec.get("fix_ok", False))
        if not is_failure:
            continue

        label, cause, proposed = classify_failure_label(entry)
        triaged.append(
            TriagedFailure(
                fault_id=entry.get("fault_id", "unknown"),
                incident_id=rec.get("incident_id", "unknown"),
                label=label,
                cause=cause,
                proposed_change=proposed,
            )
        )
        counts[label] += 1

    total_failures = len(triaged)
    if sum(counts.values()) != total_failures:
        raise AssertionError("Triage label counts do not sum to total failures")

    return {
        "total_runs": len(runs),
        "total_failures": total_failures,
        "counts_by_label": counts,
        "failures": [t.to_dict() for t in triaged],
    }


def write_triage_artifacts(
    results_path: Union[str, Path],
    *,
    json_out: Optional[Union[str, Path]] = None,
    md_out: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Load results JSON, build triage sheet, and write JSON + Markdown artifacts."""
    res_file = Path(results_path)
    payload = json.loads(res_file.read_text(encoding="utf-8"))
    triage = build_triage_sheet(payload)

    j_path = Path(json_out) if json_out else res_file.parent / "triage_v1.json"
    m_path = Path(md_out) if md_out else res_file.parent / "triage_v1.md"
    j_path.parent.mkdir(parents=True, exist_ok=True)
    m_path.parent.mkdir(parents=True, exist_ok=True)

    j_path.write_text(json.dumps(triage, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Benchmark v1 Failure Triage Sheet",
        "",
        f"- **Total Runs:** {triage['total_runs']}",
        f"- **Total Failures:** {triage['total_failures']}",
        "- **Counts by Label:** " + ", ".join(f"`{k}`: {v}" for k, v in triage["counts_by_label"].items()),
        "",
        "| Fault ID | Label | One-Line Cause | Proposed Change |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for f in triage["failures"]:
        lines.append(f"| `{f['fault_id']}` | `{f['label']}` | {f['cause']} | {f['proposed_change']} |")

    m_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return triage
