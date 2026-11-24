"""Day 4 verifier acceptance cases and worktree cleanup."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from verifier.sandbox import SandboxVerifier


class SandboxVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        target = self.root / "target-app" / "services" / "orders" / "app.py"
        target.parent.mkdir(parents=True)
        target.write_text("def answer():\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            ["git", "-c", "user.name=tests", "-c", "user.email=tests@example.com", "commit", "-qm", "base"],
            cwd=self.root,
            check=True,
        )
        self.target = "target-app/services/orders/app.py"
        self.good_patch = self._patch("return 2")
        self.bad_patch = self._patch("return 3")
        self.command = [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'target-app/services/orders'); "
            "from app import answer; assert answer() == 2",
        ]
        self.verifier = SandboxVerifier(self.root, use_container=False)

    def tearDown(self):
        self.temp.cleanup()

    def _patch(self, replacement):
        return (
            f"diff --git a/{self.target} b/{self.target}\n"
            f"--- a/{self.target}\n+++ b/{self.target}\n"
            "@@ -1,2 +1,2 @@\n def answer():\n-    return 1\n"
            f"+    {replacement}\n"
        )

    def _verify(self, patch):
        return self.verifier.verify(
            "inc-test", patch, target_file=self.target,
            reproduction_command=self.command, test_command=self.command,
        )

    def test_good_patch_passes_tests_and_reproduction(self):
        result = self._verify(self.good_patch)
        self.assertTrue(result.accepted)
        self.assertEqual(result.verification.verdict, "PASS", msg=f"{result.error}\n{result.unit_test_output}\n{result.reproduction_output}")
        self.assertTrue(result.verification.tests_passed)
        self.assertTrue(result.verification.repro_fixed)
        self.assertFalse(result.verification.canary_healthy)  # Day 5 stage, not part 1

    def test_bad_patch_fails_tests_and_reproduction(self):
        result = self._verify(self.bad_patch)
        self.assertEqual(result.verification.verdict, "FAIL")
        self.assertFalse(result.verification.tests_passed)

    def test_empty_patch_fails_clearly(self):
        result = self._verify("")
        self.assertFalse(result.accepted)
        self.assertEqual(result.error, "Patch is empty")

    def test_forbidden_path_is_rejected(self):
        forbidden = self.good_patch.replace(self.target, "README.md")
        result = self._verify(forbidden)
        self.assertFalse(result.accepted)
        self.assertIn("only modify", result.error)

    def test_worktrees_are_removed_after_runs(self):
        self._verify(self.good_patch)
        sandbox_root = self.root.parent / ".nightshift-sandboxes"
        self.assertEqual(list(sandbox_root.iterdir()), [])
        registered = self.root / ".git" / "worktrees"
        self.assertFalse(registered.exists() and list(registered.iterdir()))


if __name__ == "__main__":
    unittest.main()
