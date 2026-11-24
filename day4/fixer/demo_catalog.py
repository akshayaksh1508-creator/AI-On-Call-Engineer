"""Deterministic demonstration catalog for five deliberately seeded simple faults."""
from pathlib import Path
import difflib
from day4.fixer.fixer import Fixer

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "examples" / "target_app"
FIXES = {
    "fault_01": ("def calculate_total(items):\n    # Bug: the last item is omitted.\n    return sum(items[:-1])\n",
                 "def calculate_total(items):\n    return sum(items)\n",
                 "T2", "Off-by-one slicing omitted the final line item."),
    "fault_02": ("def normalize_status(status):\n    # Bug: status is not normalized before comparison.\n    if status == 'paid':\n        return 'complete'\n    return 'pending'\n",
                 "def normalize_status(status):\n    if status.strip().lower() == 'paid':\n        return 'complete'\n    return 'pending'\n",
                 "T2", "Input status was compared without trimming and case normalization."),
    "fault_03": ("def retry_delay(attempt):\n    # Bug: exponential backoff starts one attempt too early.\n    return 2 ** (attempt - 1)\n",
                 "def retry_delay(attempt):\n    return 2 ** attempt\n",
                 "T2", "Exponential backoff exponent was one attempt behind."),
    "fault_04": ("def parse_quantity(payload):\n    # Bug: missing quantity raises KeyError.\n    return int(payload['quantity'])\n",
                 "def parse_quantity(payload):\n    return int(payload.get('quantity', 0))\n",
                 "T2", "Missing quantity was not handled with a safe default."),
    "fault_05": ("def is_success(status_code):\n    # Bug: redirects are incorrectly treated as failures.\n    return 200 <= status_code < 300\n",
                 "def is_success(status_code):\n    return 200 <= status_code < 400\n",
                 "T2", "Successful redirect responses were incorrectly classified as failures.")
}
EVIDENCE = {
    "fault_01":"LOG-ORDER-001", "fault_02":"LOG-STATUS-002",
    "fault_03":"METRIC-RETRY-003", "fault_04":"TRACE-PARSE-004",
    "fault_05":"LOG-HTTP-005"
}
class DemoCatalog:
    def __init__(self):
        self.fixer = Fixer()

    def proposal(self, fault_id):
        if fault_id not in FIXES:
            raise ValueError(f"Unknown demo fault: {fault_id}")
        old, new, tier, reason = FIXES[fault_id]
        path = f"src/{fault_id}.py"
        diff = "".join(difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"a/{path}", tofile=f"b/{path}"
        ))
        test_path = f"tests/test_{fault_id}.py"
        return self.fixer.build_proposal(
            proposal_id=f"proposal-{fault_id}", diff=diff, fault_id=fault_id,
            rationale=reason,
            expected_metric_effect=f"Regression for {fault_id} stops reproducing; affected request returns expected result.",
            regression_test=f"python -m unittest {test_path[:-3].replace('/', '.')}",
            evidence_ids=[EVIDENCE[fault_id]], fix_type="patch", risk_tier=tier,
            branch_name=f"fix/{fault_id}"
        )
