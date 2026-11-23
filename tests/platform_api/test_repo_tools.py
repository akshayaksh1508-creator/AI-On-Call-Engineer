import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import subprocess, tempfile, unittest
from pathlib import Path

from platform_api.repo_tools import RepoToolError, RepoTools

ENV = {**os.environ, "GIT_AUTHOR_NAME": "dev", "GIT_AUTHOR_EMAIL": "d@x", "GIT_COMMITTER_NAME": "dev", "GIT_COMMITTER_EMAIL": "d@x"}


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


class RepoToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "mono"
        (self.repo / "target-app" / "payments").mkdir(parents=True)
        (self.repo / "other").mkdir()
        sh("git", "init", "-q", cwd=self.repo)
        (self.repo / "target-app" / "payments" / "app.py").write_text("def charge():\n    return 1\n")
        (self.repo / "target-app" / ".env").write_text("TOKEN=SECRET_VALUE_1\n")
        (self.repo / "target-app" / "secrets.txt").write_text("hush\n")
        (self.repo / "other" / "outside.txt").write_text("outside\n")
        sh("git", "add", ".", cwd=self.repo)
        sh("git", "commit", "-qm", "initial", cwd=self.repo)
        self.c1 = sh("git", "rev-parse", "HEAD", cwd=self.repo)
        (self.repo / "target-app" / "payments" / "app.py").write_text("def charge():\n    return None.amount\n")
        (self.repo / "target-app" / ".env").write_text("TOKEN=SECRET_VALUE_2\n")
        sh("git", "commit", "-qam", "break charge", cwd=self.repo)
        self.c2 = sh("git", "rev-parse", "HEAD", cwd=self.repo)
        self.has_symlink = False
        try:
            os.symlink(self.repo / "other" / "outside.txt", self.repo / "target-app" / "link.txt")
            self.has_symlink = True
        except OSError:
            pass
        self.t = RepoTools(self.repo, root_subdir="target-app", max_bytes=60)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_file_working_tree_and_ref(self):
        self.assertIn("None.amount", self.t.read_file("payments/app.py")["content"])
        self.assertIn("return 1", self.t.read_file("payments/app.py", ref=self.c1)["content"])

    def test_line_range_and_truncation(self):
        r = self.t.read_file("payments/app.py", start_line=2, end_line=2)
        self.assertEqual(r["content"].strip(), "return None.amount")
        big = RepoTools(self.repo, root_subdir="target-app", max_bytes=5)
        r = big.read_file("payments/app.py")
        self.assertTrue(r["truncated"])
        self.assertEqual(len(r["content"]), 5)

    def test_path_escapes_and_secrets_rejected(self):
        for bad in ("../other/outside.txt", "/etc/passwd", "payments/../../other/outside.txt", ".env", "secrets.txt", "a\\b", "x\x00y"):
            with self.assertRaises(RepoToolError, msg=repr(bad)) as cm:
                self.t.read_file(bad)
            self.assertEqual(cm.exception.status, 403, bad)

    def test_symlink_escape_rejected(self):
        if not getattr(self, "has_symlink", False):
            self.skipTest("symlinks require elevated privileges on Windows")
        with self.assertRaises(RepoToolError) as cm:
            self.t.read_file("link.txt")
        self.assertEqual(cm.exception.status, 403)

    def test_missing_file_is_404(self):
        with self.assertRaises(RepoToolError) as cm:
            self.t.read_file("payments/nope.py")
        self.assertEqual(cm.exception.status, 404)

    def test_git_log_path_since_limit(self):
        log = self.t.git_log(path="payments/app.py")
        self.assertEqual([c["subject"] for c in log], ["break charge", "initial"])
        self.assertEqual(len(self.t.git_log(n=1)), 1)
        newest = log[0]["ts"]
        self.assertEqual([c["subject"] for c in self.t.git_log(since=newest + 100)], [])
        self.assertEqual(self.t.git_log(until=newest - 100), [] if log[1]["ts"] > newest - 100 else self.t.git_log(until=newest - 100))

    def test_git_diff_commit_and_secret_exclusion(self):
        d = self.t.git_diff(commit=self.c2)
        self.assertIn("+    return None.amount", d["diff"])
        self.assertNotIn("SECRET_VALUE", d["diff"])
        self.assertEqual([f["path"] for f in d["files"]], ["target-app/payments/app.py"])
        d2 = self.t.git_diff(base=self.c1, head=self.c2, path="payments")
        self.assertIn("None.amount", d2["diff"])

    def test_ref_injection_rejected(self):
        for bad in ("--output=/tmp/x", "HEAD;ls", "a..b"):
            with self.assertRaises(RepoToolError):
                self.t.git_log(ref=bad)
            with self.assertRaises(RepoToolError):
                self.t.git_diff(commit=bad)
        with self.assertRaises(RepoToolError):
            self.t.git_diff()


if __name__ == "__main__":
    unittest.main()
