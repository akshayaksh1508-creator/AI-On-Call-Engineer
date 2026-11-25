"""Confidence Calibration & Threshold Auto-Adjustment (Day 8 Task B2).

Bins historical RCA/fix outcomes by confidence score (`[0.0, 0.5)`, `[0.5, 0.8)`,
`[0.8, 1.0]`), builds a calibration table, and enforces the safety rule:
  - In the >= 0.8 confidence bin, accuracy must be >= 80%; otherwise the
    autonomous action threshold is automatically raised.

Owner: Person B (Brain & Trust)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Sequence, Tuple


DEFAULT_BINS: Tuple[Tuple[str, float, float], ...] = (
    ("0.0-0.5", 0.0, 0.5),
    ("0.5-0.8", 0.5, 0.8),
    ("0.8-1.0", 0.8, 1.01),
)


@dataclass
class ConfidenceBin:
    """Calibration statistics for a single confidence bucket."""

    label: str
    low: float
    high: float
    count: int
    correct_count: int
    accuracy: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationReport:
    """Full confidence calibration table and threshold recommendation."""

    bins: List[ConfidenceBin]
    high_conf_bin_accuracy: float
    high_conf_target: float
    previous_threshold: float
    recommended_threshold: float
    threshold_raised: bool
    calibrated_ok: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bins": [b.to_dict() for b in self.bins],
            "high_conf_bin_accuracy": self.high_conf_bin_accuracy,
            "high_conf_target": self.high_conf_target,
            "previous_threshold": self.previous_threshold,
            "recommended_threshold": self.recommended_threshold,
            "threshold_raised": self.threshold_raised,
            "calibrated_ok": self.calibrated_ok,
        }


def calibrate_confidence(
    samples: Sequence[Dict[str, Any]],
    *,
    current_threshold: float = 0.80,
    target_high_conf_accuracy: float = 0.80,
) -> CalibrationReport:
    """Compute binned calibration table and raise threshold if >=0.8 bin accuracy < 80%.

    Each sample dict must contain `confidence: float` and `correct: bool`.
    """
    bin_results: List[ConfidenceBin] = []

    for label, lo, hi in DEFAULT_BINS:
        bucket = [s for s in samples if lo <= float(s.get("confidence", 0.0)) < hi]
        cnt = len(bucket)
        correct_cnt = sum(1 for s in bucket if bool(s.get("correct", False)))
        acc = round(correct_cnt / cnt, 4) if cnt > 0 else 0.0
        bin_results.append(
            ConfidenceBin(
                label=label,
                low=lo,
                high=min(1.0, hi),
                count=cnt,
                correct_count=correct_cnt,
                accuracy=acc,
            )
        )

    high_bin = bin_results[-1]  # 0.8-1.0
    high_acc = high_bin.accuracy

    # Enforce rule: >=0.8 bin must have >=80% accuracy; otherwise raise threshold
    calibrated_ok = high_bin.count > 0 and high_acc >= target_high_conf_accuracy
    threshold_raised = False
    recommended = current_threshold

    if not calibrated_ok:
        threshold_raised = True
        # Search higher sub-thresholds (0.85, 0.90, 0.95) for a stricter gate
        for candidate in (0.85, 0.90, 0.95):
            if candidate <= current_threshold:
                continue
            sub = [s for s in samples if float(s.get("confidence", 0.0)) >= candidate]
            if sub and (sum(1 for s in sub if bool(s.get("correct", False))) / len(sub)) >= target_high_conf_accuracy:
                recommended = candidate
                break
        else:
            recommended = min(0.95, round(max(current_threshold + 0.10, 0.90), 2))

    return CalibrationReport(
        bins=bin_results,
        high_conf_bin_accuracy=high_acc,
        high_conf_target=target_high_conf_accuracy,
        previous_threshold=current_threshold,
        recommended_threshold=recommended,
        threshold_raised=threshold_raised,
        calibrated_ok=calibrated_ok,
    )


def format_calibration_markdown(report: CalibrationReport) -> str:
    """Format CalibrationReport as a Markdown table."""
    lines = [
        "| Confidence Bin | Count | Correct | Accuracy |",
        "| :--- | :---: | :---: | :---: |",
    ]
    for b in report.bins:
        lines.append(f"| `{b.label}` | {b.count} | {b.correct_count} | {b.accuracy:.1%} |")
    lines.append("")
    lines.append(
        f"- **>= 0.8 Bin Accuracy:** {report.high_conf_bin_accuracy:.1%} "
        f"(Target: >= {report.high_conf_target:.0%})"
    )
    lines.append(
        f"- **Threshold:** `{report.previous_threshold:.2f}` -> `{report.recommended_threshold:.2f}` "
        f"(Raised: `{report.threshold_raised}`)"
    )
    return "\n".join(lines) + "\n"
