
"""Check candidate generation against the five actual faulty source files."""

from pathlib import Path

import pytest

from contracts.models import Hypothesis
from fixer.fixer import Fixer


ROOT = Path(__file__).resolve().parents[2]

FAULTS = [
    ("fault_001_bad_deploy", "orders", "NoneType discount TypeError"),
    ("fault_002_off_by_one", "orders", "IndexError paginate_records"),
    ("fault_003_wrong_status_code", "payments", "declined payment HTTP 402"),
    ("fault_004_bad_parsing", "gateway", "ISO timestamp strptime trailing Z"),
    ("fault_005_unhandled_exception", "orders", "ZeroDivisionError division by zero"),
]


@pytest.mark.parametrize("fault_id,service,cause", FAULTS)
def test_actual_fault_source_generates_candidate(fault_id, service, cause):
    fixture = ROOT / "faults" / "catalog" / fault_id
    source = (fixture / "buggy_app.py").read_text(encoding="utf-8")

    hypothesis = Hypothesis(
        cause=cause,
        category="code",
        confidence=0.95,
        evidence_ids=["ev_test"],
    )

    fixer = Fixer(ROOT)
    target = f"target-app/services/{service}/app.py"

    patch, rationale = fixer.generate_candidate_diff(
        source,
        target,
        hypothesis,
    )

    assert patch
    assert f"diff --git a/{target} b/{target}" in patch
    assert rationale
    assert "patched_app.py" not in patch
