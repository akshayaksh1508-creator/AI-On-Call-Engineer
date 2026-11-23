"""Day 4 generated test validation and fail-before/pass-after proof."""

import sys
import tempfile
import unittest
from pathlib import Path

from fixer.regression import RegressionTestError, verify_fail_then_pass, write_regression_test


class RegressionGenerationDay4Tests(unittest.TestCase):
    def test_generated_test_must_be_syntactic_and_assertive(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RegressionTestError):
                write_regression_test("fault_001", "not python !!!", folder)
            with self.assertRaisesRegex(RegressionTestError, "assertion"):
                write_regression_test(
                    "fault_001", "import unittest\nclass TestEmpty(unittest.TestCase):\n    def test_empty(self):\n        self.fail()\n", folder
                )

    def test_regression_fails_before_and_passes_after(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before, after = root / "before", root / "after"
            before.mkdir()
            after.mkdir()
            (before / "app.py").write_text("def answer(): return 1\n", encoding="utf-8")
            (after / "app.py").write_text("def answer(): return 2\n", encoding="utf-8")
            generated = write_regression_test(
                "fault_001",
                "import unittest\nfrom app import answer\n\n"
                "class TestAnswer(unittest.TestCase):\n"
                "    def test_answer_regression(self):\n        self.assertEqual(answer(), 2)\n\n"
                "if __name__ == '__main__':\n    unittest.main()\n",
                root,
            )
            result = verify_fail_then_pass(generated, before, after, timeout=30)
            self.assertTrue(result.verified, msg=f"before: {result.before_output}\nafter: {result.after_output}")


if __name__ == "__main__":
    unittest.main()
