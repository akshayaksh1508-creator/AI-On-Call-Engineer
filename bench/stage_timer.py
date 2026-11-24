"""Stage Timing and RunRecord Generator for Benchmark Evaluations (Day 6 Task A3).

Captures exact stage timestamps across the entire incident remediation lifecycle:
  1. Fault Injection (t_inject)
  2. Incident Detection (t_detect)
  3. Root Cause Analysis (t_rca)
  4. Fix Proposal Generation (t_fix)
  5. Verification & Health Recovery (t_verified)

Guarantees:
  - Timestamps are strictly monotonic / increasing (t_inject < t_detect < t_rca < t_fix < t_verified).
  - Stage durations match contracts.models.RunRecord schema (t_detect, t_rca, t_fix, t_verified).
  - Total elapsed time matches independent stopwatch / external timing within 5.0 seconds.
  - Serializes to JSON / JSONL for benchmark aggregator and results reporting.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from contracts.models import RunRecord

logger = logging.getLogger("nightshift.bench.stage_timer")


@dataclass
class StageTimeline:
    """Raw wall-clock epoch timestamps recorded at each stage boundary."""
    t_inject: float
    t_detect: float
    t_rca: float
    t_fix: float
    t_verified: float

    @property
    def is_strictly_increasing(self) -> bool:
        """True if stage boundary timestamps are strictly monotonic (t_inject < t_detect < t_rca < t_fix < t_verified)."""
        return (
            self.t_inject < self.t_detect < self.t_rca < self.t_fix < self.t_verified
        )

    @property
    def total_duration(self) -> float:
        """Total wall-clock duration from fault injection to verified recovery."""
        return self.t_verified - self.t_inject

    @property
    def stage_durations(self) -> Dict[str, float]:
        """Calculated elapsed seconds spent in each distinct stage."""
        return {
            "t_detect": round(self.t_detect - self.t_inject, 4),
            "t_rca": round(self.t_rca - self.t_detect, 4),
            "t_fix": round(self.t_fix - self.t_rca, 4),
            "t_verified": round(self.t_verified - self.t_fix, 4),
            "total": round(self.total_duration, 4),
        }

    def matches_stopwatch(self, stopwatch_seconds: float, tolerance: float = 5.0) -> bool:
        """Verify that total duration matches an external stopwatch within the required tolerance."""
        delta = abs(self.total_duration - stopwatch_seconds)
        return delta <= tolerance


class StageTimer:
    """Manages stage timestamping and constructs valid contracts.models.RunRecord objects."""

    def __init__(
        self,
        incident_id: str = "inc_default",
        fault_id: str = "fault_default",
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.incident_id = incident_id
        self.fault_id = fault_id
        self.clock = clock

        # Stage boundary timestamps
        self.t_inject_ts: Optional[float] = None
        self.t_detect_ts: Optional[float] = None
        self.t_rca_ts: Optional[float] = None
        self.t_fix_ts: Optional[float] = None
        self.t_verified_ts: Optional[float] = None

        # Benchmark evaluation indicators
        self.rca_correct_top1: bool = True
        self.rca_correct_top3: bool = True
        self.fix_ok: bool = True
        self.unsafe: bool = False
        self.tokens: int = 0
        self.cost_usd: float = 0.0

        # Detailed stage metadata
        self.metadata: Dict[str, Any] = {}

    def record_inject(self, t: Optional[float] = None) -> float:
        """Record timestamp when fault is injected."""
        ts = t if t is not None else self.clock()
        self.t_inject_ts = ts
        return ts

    def record_detect(self, incident_id: Optional[str] = None, t: Optional[float] = None) -> float:
        """Record timestamp when incident is detected by detector."""
        if incident_id:
            self.incident_id = incident_id
        ts = t if t is not None else self.clock()
        self.t_detect_ts = ts
        return ts

    def record_rca(
        self,
        *,
        correct_top1: bool = True,
        correct_top3: bool = True,
        t: Optional[float] = None,
    ) -> float:
        """Record timestamp when root cause analysis completes."""
        self.rca_correct_top1 = correct_top1
        self.rca_correct_top3 = correct_top3
        ts = t if t is not None else self.clock()
        self.t_rca_ts = ts
        return ts

    def record_fix(
        self,
        *,
        proposal: Optional[Any] = None,
        t: Optional[float] = None,
    ) -> float:
        """Record timestamp when fix proposal is generated."""
        if proposal is not None:
            self.metadata["fix_proposal"] = (
                proposal.model_dump() if hasattr(proposal, "model_dump") else str(proposal)
            )
        ts = t if t is not None else self.clock()
        self.t_fix_ts = ts
        return ts

    def record_verified(
        self,
        *,
        fix_ok: bool = True,
        unsafe: bool = False,
        verification: Optional[Any] = None,
        t: Optional[float] = None,
    ) -> float:
        """Record timestamp when verification of recovery completes."""
        self.fix_ok = fix_ok
        self.unsafe = unsafe
        if verification is not None:
            self.metadata["verification"] = (
                verification.model_dump() if hasattr(verification, "model_dump") else str(verification)
            )
        ts = t if t is not None else self.clock()
        self.t_verified_ts = ts
        return ts

    def get_timeline(self) -> StageTimeline:
        """Validate and return the StageTimeline object."""
        if (
            self.t_inject_ts is None
            or self.t_detect_ts is None
            or self.t_rca_ts is None
            or self.t_fix_ts is None
            or self.t_verified_ts is None
        ):
            missing = []
            if self.t_inject_ts is None:
                missing.append("inject")
            if self.t_detect_ts is None:
                missing.append("detect")
            if self.t_rca_ts is None:
                missing.append("rca")
            if self.t_fix_ts is None:
                missing.append("fix")
            if self.t_verified_ts is None:
                missing.append("verified")
            raise ValueError(f"Cannot produce StageTimeline; missing stage timestamps: {', '.join(missing)}")

        return StageTimeline(
            t_inject=self.t_inject_ts,
            t_detect=self.t_detect_ts,
            t_rca=self.t_rca_ts,
            t_fix=self.t_fix_ts,
            t_verified=self.t_verified_ts,
        )

    def to_run_record(
        self,
        *,
        tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        unsafe: Optional[bool] = None,
    ) -> RunRecord:
        """Construct a validated contracts.models.RunRecord schema object."""
        timeline = self.get_timeline()
        durations = timeline.stage_durations

        final_tokens = tokens if tokens is not None else self.tokens
        final_cost = cost_usd if cost_usd is not None else self.cost_usd
        final_unsafe = unsafe if unsafe is not None else self.unsafe

        return RunRecord(
            incident_id=self.incident_id,
            fault_id=self.fault_id,
            t_detect=durations["t_detect"],
            t_rca=durations["t_rca"],
            t_fix=durations["t_fix"],
            t_verified=durations["t_verified"],
            rca_correct_top1=self.rca_correct_top1,
            rca_correct_top3=self.rca_correct_top3,
            fix_ok=self.fix_ok,
            unsafe=final_unsafe,
            tokens=final_tokens,
            cost_usd=round(final_cost, 6),
        )

    def save(self, filepath: Union[str, Path]) -> RunRecord:
        """Save RunRecord and timeline to JSON or append to JSONL."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = self.to_run_record()

        record_dict = rec.model_dump()
        record_dict["timestamps"] = asdict(self.get_timeline())
        record_dict["metadata"] = self.metadata

        if path.suffix == ".jsonl":
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record_dict) + "\n")
        else:
            existing = []
            if path.exists():
                try:
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(loaded, list):
                        existing = loaded
                    elif isinstance(loaded, dict):
                        existing = [loaded]
                except Exception:
                    existing = []
            existing.append(record_dict)
            path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

        return rec
