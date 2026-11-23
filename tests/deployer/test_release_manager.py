import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import subprocess, tempfile, unittest
from pathlib import Path

from deployer.changes import ChangeLog
from deployer.release_manager import DeployError, ReleaseManager
from deployer.runners import ComposeRunner, NoopRunner

ENV = {**os.environ, "GIT_AUTHOR_NAME": "dev", "GIT_AUTHOR_EMAIL": "d@x", "GIT_COMMITTER_NAME": "dev", "GIT_COMMITTER_EMAIL": "d@x"}


def sh(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def make_repo(root: Path):
    repo = root / "app"
    repo.mkdir()
    sh("git", "init", "-q", cwd=repo)
    shas = []
    for i in (1, 2, 3):
        (repo / "version.txt").write_text(f"v{i}")
        sh("git", "add", ".", cwd=repo)
        sh("git", "commit", "-qm", f"release v{i}", cwd=repo)
        shas.append(sh("git", "rev-parse", "HEAD", cwd=repo))
    return repo, shas


class ReleaseManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.repo, self.shas = make_repo(root)
        self.log = ChangeLog(root / "data" / "changes.jsonl")
        self.runner = NoopRunner()
        self.mgr = ReleaseManager(self.repo, root / "data" / "state.json", self.log, self.runner, releases_dir=root / "rel")

    def tearDown(self):
        self.tmp.cleanup()

    def test_deploy_changes_version_and_emits_event(self):
        self.mgr.bootstrap("payments", self.shas[0])
        res = self.mgr.deploy("payments", self.shas[1], author="alice")
        self.assertTrue(res["changed"])
        self.assertEqual(self.mgr.current("payments"), self.shas[1])
        ev = self.log.list(service="payments")
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["type"], ev[0]["from_ref"], ev[0]["to_ref"]), ("deploy", self.shas[0], self.shas[1]))
        self.assertEqual(ev[0]["meta"]["subject"], "release v2")
        rel_dir = Path(self.runner.calls[-1][2])
        self.assertEqual((rel_dir / "version.txt").read_text(), "v2")

    def test_same_ref_is_idempotent(self):
        self.mgr.bootstrap("orders", self.shas[1])
        self.assertFalse(self.mgr.deploy("orders", self.shas[1])["changed"])
        self.assertEqual(self.log.list(), [])

    def test_rollback_restores_previous_and_emits_event(self):
        self.mgr.bootstrap("payments", self.shas[0])
        self.mgr.deploy("payments", self.shas[1])
        self.mgr.deploy("payments", self.shas[2])
        r = self.mgr.rollback("payments", author="agent")
        self.assertEqual(r["to"], self.shas[1])
        self.assertEqual(self.mgr.current("payments"), self.shas[1])
        r = self.mgr.rollback("payments")
        self.assertEqual(self.mgr.current("payments"), self.shas[0])
        types = [e["type"] for e in self.log.list(service="payments")]
        self.assertEqual(types, ["deploy", "deploy", "rollback", "rollback"])
        with self.assertRaises(DeployError):
            self.mgr.rollback("payments")  # nothing left

    def test_events_are_ordered_and_filterable(self):
        self.mgr.bootstrap("gateway", self.shas[0])
        self.mgr.deploy("gateway", self.shas[1])
        self.mgr.rollback("gateway")
        evs = self.log.list()
        self.assertEqual([e["ts"] for e in evs], sorted(e["ts"] for e in evs))
        self.assertEqual(len(self.log.list(type="rollback")), 1)
        self.assertEqual(self.log.list(since=evs[-1]["ts"] + 1), [])

    def test_failed_deploy_keeps_state_and_records_failure(self):
        self.mgr.bootstrap("payments", self.shas[0])
        self.runner.fail_shas.add(self.shas[1])
        with self.assertRaises(DeployError):
            self.mgr.deploy("payments", self.shas[1])
        self.assertEqual(self.mgr.current("payments"), self.shas[0])
        self.assertEqual(self.log.list()[-1]["type"], "deploy_failed")
        self.assertEqual(self.runner.calls[-1][3], self.shas[0])  # previous release restored

    def test_bad_refs_and_services_rejected(self):
        for bad in ("--upload-pack=x", "a..b", "; rm -rf /", "", "nope-not-a-ref"):
            with self.assertRaises(DeployError, msg=bad):
                self.mgr.deploy("payments", bad)
        with self.assertRaises(DeployError):
            self.mgr.deploy("database", self.shas[0])

    def test_compose_runner_builds_expected_command_and_checks_version(self):
        calls = []
        runner = ComposeRunner(
            "docker-compose.yml", {"payments": "http://x/health"}, health_timeout=2,
            exec_fn=lambda cmd, env: calls.append((cmd, env)) or "",
            health_fn=lambda url: (True, self.shas[1][:7]),
        )
        res = runner.deploy("payments", Path("/tmp/rel"), self.shas[1])
        self.assertTrue(res.ok)
        cmd, env = calls[0]
        self.assertEqual(cmd[:4], ["docker", "compose", "-f", "docker-compose.yml"])
        self.assertIn("--no-deps", cmd)
        self.assertEqual(env["PAYMENTS_RELEASE_DIR"], "/tmp/rel")
        self.assertEqual(env["PAYMENTS_VERSION"], self.shas[1])


if __name__ == "__main__":
    unittest.main()
