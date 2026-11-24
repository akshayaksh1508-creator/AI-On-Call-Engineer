import subprocess, sys, unittest
from pathlib import Path
from day4.cli import ensure_git_repo, verify, TARGET
from day4.verifier.sandbox import SandboxVerifier

class Day4AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_git_repo()

    def test_good_patch_passes(self):
        _, result = verify("fault_01")
        self.assertEqual(result.verdict, "pass")
        self.assertTrue(result.tests_passed and result.repro_fixed and result.worktree_cleaned)

    def test_bad_patch_fails(self):
        # A syntactically valid no-op patch cannot fix the seeded bug; tests and repro fail.
        patch = """--- a/src/fault_01.py
+++ b/src/fault_01.py
@@ -1,3 +1,3 @@
 def calculate_total(items):
-    # Bug: the last item is omitted.
-    return sum(items[:-1])
+    # Still wrong: last item remains omitted.
+    return sum(items[:-1])
"""
        verifier = SandboxVerifier(TARGET, allowed_paths=("src/", "tests/"))
        result = verifier.verify(patch, [sys.executable, "-m", "unittest", "tests.test_fault_01"],
                                 [sys.executable, "scripts/reproduce.py", "fault_01"])
        self.assertEqual(result.verdict, "fail")

    def test_empty_patch_is_rejected(self):
        verifier = SandboxVerifier(TARGET, allowed_paths=("src/", "tests/"))
        result = verifier.verify("", [sys.executable, "-m", "unittest"], [sys.executable, "-V"])
        self.assertEqual(result.verdict, "fail")
        self.assertFalse(result.patch_applied)

    def test_forbidden_path_is_rejected(self):
        patch = """--- a/.env
+++ b/.env
@@ -1 +1 @@
-OLD
+SECRET=bad
"""
        verifier = SandboxVerifier(TARGET, allowed_paths=("src/", "tests/"))
        result = verifier.verify(patch, [sys.executable, "-m", "unittest"], [sys.executable, "-V"])
        self.assertEqual(result.verdict, "fail")
        self.assertFalse(result.patch_applied)

    def test_all_five_simple_faults_pass_sandbox(self):
        outcomes = [verify(f"fault_{i:02d}")[1].verdict for i in range(1, 6)]
        self.assertEqual(outcomes, ["pass"] * 5)

if __name__ == "__main__":
    unittest.main()
