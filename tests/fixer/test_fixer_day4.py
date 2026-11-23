"""Day 4 fixer scope, evidence, applicability, and selection checks."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from contracts.models import Evidence, Hypothesis
from fixer.fixer import Fixer, FixValidationError, select_fix_type


class FixerDay4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = self.root / "target-app" / "services" / "orders" / "app.py"
        self.target.parent.mkdir(parents=True)
        self.target.write_text("def value():\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=tests", "-c", "user.email=tests@example.com", "commit", "-qm", "base"],
            cwd=self.root,
            check=True,
        )
        self.hypothesis = Hypothesis(
            cause="Incorrect return value", category="code", confidence=0.9,
            evidence_ids=["ev_1"],
        )
        self.evidence = [Evidence(id="ev_1", type="log", ref="log:1", excerpt="error", ts="now")]
        self.diff = (
            "diff --git a/target-app/services/orders/app.py b/target-app/services/orders/app.py\n"
            "--- a/target-app/services/orders/app.py\n"
            "+++ b/target-app/services/orders/app.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def value():\n"
            "-    return 1\n"
            "+    return 2\n"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_applicable_patch_is_returned(self):
        result = Fixer(self.root).validate_diff(self.diff, self.hypothesis, self.evidence)
        self.assertIn("+    return 2", result)

    def test_stale_or_malformed_patch_has_clear_error(self):
        with self.assertRaisesRegex(FixValidationError, "does not apply"):
            Fixer(self.root).validate_diff(self.diff.replace("return 1", "return 9"), self.hypothesis, self.evidence)
        with self.assertRaisesRegex(FixValidationError, "empty"):
            Fixer(self.root).validate_diff("", self.hypothesis, self.evidence)

    def test_forbidden_path_and_unknown_evidence_are_rejected(self):
        unsafe = self.diff.replace("target-app/services/orders/app.py", "README.md")
        with self.assertRaisesRegex(FixValidationError, "outside the allowlist"):
            Fixer(self.root).validate_diff(unsafe, self.hypothesis, self.evidence)
        with self.assertRaisesRegex(FixValidationError, "unknown evidence"):
            Fixer(self.root).validate_diff(
                self.diff, self.hypothesis, [Evidence(id="other", type="log", ref="x", excerpt="x", ts="now")]
            )

    def test_fix_type_selection_table(self):
        rows = [
            # recent deploy, clean revert, category, explicit config, expected
            (True, True, "code", False, "rollback"),
            (True, False, "code", False, "patch"),
            (False, True, "code", False, "patch"),
            (False, False, "config", False, "config"),
            (False, False, "code", True, "config"),
            (True, True, "config", False, "config"),
            (True, False, "cross_service", False, "patch"),
            (False, True, "dependency", False, "patch"),
            (True, True, "resource", False, "rollback"),
            (False, False, "unknown", False, "patch"),
        ]
        for recent, clean, category, config, expected in rows:
            with self.subTest(recent=recent, clean=clean, category=category, config=config):
                hypothesis = self.hypothesis.model_copy(update={"category": category})
                self.assertEqual(
                    select_fix_type(
                        hypothesis, recent_deploy=recent, clean_revert=clean, config_fault=config
                    ),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
