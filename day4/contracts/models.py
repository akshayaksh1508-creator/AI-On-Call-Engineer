"""Dependency-free FixProposal contract with strict validation."""
from dataclasses import asdict, dataclass
from typing import Literal
import json
from pathlib import Path

@dataclass
class FixProposal:
    proposal_id: str
    type: Literal["patch", "rollback", "config"]
    diff: str
    risk_tier: Literal["T1", "T2", "T3"]
    rationale: str
    expected_metric_effect: str
    regression_test: str
    evidence_ids: list[str]
    fault_id: str | None = None
    branch_name: str | None = None

    def validate(self) -> "FixProposal":
        if not self.proposal_id.strip() or not self.rationale.strip():
            raise ValueError("proposal_id and rationale are required")
        if self.type not in {"patch", "rollback", "config"}:
            raise ValueError("type must be patch, rollback, or config")
        if self.risk_tier not in {"T1", "T2", "T3"}:
            raise ValueError("risk_tier must be T1, T2, or T3")
        if not self.expected_metric_effect.strip() or not self.regression_test.strip():
            raise ValueError("expected_metric_effect and regression_test are required")
        if not self.evidence_ids or any(not x.strip() for x in self.evidence_ids):
            raise ValueError("at least one non-empty evidence ID is required")
        return self

    def to_dict(self) -> dict:
        self.validate()
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)
