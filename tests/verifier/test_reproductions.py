"""Regression tests for the five smallest checked-in code fault scenarios."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "target-app"))
sys.path.insert(0, str(ROOT))


class TestDay4Reproductions(unittest.TestCase):
    def test_fault_001_bad_deploy(self):
        from tests.verifier.reproduce import reproduce

        reproduce("fault_001_bad_deploy")

    def test_fault_002_off_by_one(self):
        from tests.verifier.reproduce import reproduce

        reproduce("fault_002_off_by_one")

    def test_fault_003_wrong_status_code(self):
        from tests.verifier.reproduce import reproduce

        reproduce("fault_003_wrong_status_code")

    def test_fault_004_bad_parsing(self):
        from tests.verifier.reproduce import reproduce

        reproduce("fault_004_bad_parsing")

    def test_fault_005_unhandled_exception(self):
        from tests.verifier.reproduce import reproduce

        reproduce("fault_005_unhandled_exception")


if __name__ == "__main__":
    unittest.main()
