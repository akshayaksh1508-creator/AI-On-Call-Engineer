
"""Tests for evidence-driven repair generation without corrected fixtures."""

from pathlib import Path

import pytest

from contracts.models import Evidence, Hypothesis
from fixer.fixer import Fixer, FixValidationError


@pytest.fixture
def fixer(tmp_path):
    return Fixer(tmp_path, allowed_paths=("target-app/",))


def make_hypothesis(cause: str) -> Hypothesis:
    return Hypothesis(
        cause=cause,
        category="code",
        confidence=0.95,
        evidence_ids=["ev_test"],
    )


@pytest.mark.parametrize(
    ("cause", "before", "expected"),
    [
        (
            "TypeError NoneType discount code",
            'discount_code = discount["code"]',
            'discount_code = discount.get("code") if isinstance(discount, dict) else None',
        ),
        (
            "IndexError in paginate_records",
            "_next_check = records[end]",
            "if start >= len(records): return []",
        ),
        (
            "Payment declined with wrong status code",
            'return PaymentResponse(payment_id="", order_id=req.order_id, status="DECLINED", amount=req.amount, currency=req.currency)',
            'raise HTTPException(status_code=402, detail="Payment declined: Transaction exceeds safety limit or card declined")',
        ),
        (
            "ISO timestamp parser rejects trailing 'Z'",
            'return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S%z")',
            'return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))',
        ),
        (
            "ZeroDivisionError division by zero",
            "return total_discount / total_items",
            "if total_items <= 0:",
        ),
    ],
)
def test_generates_candidate_without_corrected_fixture(
    fixer,
    cause,
    before,
    expected,
):
    hypothesis = make_hypothesis(cause)

    patch, rationale = fixer.generate_candidate_diff(
        before,
        "target-app/services/test/app.py",
        hypothesis,
    )

    assert patch
    assert expected in patch
    assert rationale


def test_unknown_fault_is_not_guessed(fixer):
    hypothesis = make_hypothesis("Unknown database connection failure")

    with pytest.raises(FixValidationError):
        fixer.generate_candidate_diff(
            "def connect():\n    pass\n",
            "target-app/services/test/app.py",
            hypothesis,
        )


def test_generator_does_not_need_patched_fixture(fixer):
    hypothesis = make_hypothesis("TypeError NoneType discount code")

    source = 'discount_code = discount["code"]'

    patch, _ = fixer.generate_candidate_diff(
        source,
        "target-app/services/test/app.py",
        hypothesis,
    )

    assert "patched_app.py" not in patch
    assert 'discount.get("code")' in patch
