import unittest

from bench.day12_live_rehearsal import run_day12_live_rehearsal
from bench.env_freeze import run_env_freeze_checklist
from bench.submission_package import build_submission_package_manifest


class TestDay12A1ToA3(unittest.TestCase):
    def test_a1_env_freeze_checklist_passes(self):
        report = run_env_freeze_checklist()
        self.assertTrue(report["all_passed"], f"Env freeze failed: {report}")
        check_names = {c["name"]: c["passed"] for c in report["checks"]}
        self.assertTrue(check_names["pin_dependency_versions"])
        self.assertTrue(check_names["pre_pull_images"])
        self.assertTrue(check_names["check_disk_space"])
        self.assertTrue(check_names["confirm_api_spend_cap_and_key"])

    def test_a2_two_consecutive_live_runs_plus_curveball(self):
        report = run_day12_live_rehearsal()
        self.assertTrue(report["all_passed"], f"Live rehearsal failed: {report}")
        self.assertTrue(report["consecutive_live_runs_passed"])
        self.assertEqual(len(report["live_runs"]), 2)
        for run in report["live_runs"]:
            self.assertTrue(run["verified_recovery"])
            self.assertFalse(run["unsafe"])
        self.assertTrue(report["curveball_passed"])
        self.assertIn(report["curveball"]["outcome"], ("verified_fix", "safe_escalation"))
        self.assertFalse(report["curveball"]["unsafe"])

    def test_a3_backup_video_readme_and_submission_package(self):
        manifest = build_submission_package_manifest()
        self.assertTrue(manifest["all_passed"], f"Submission package failed: {manifest}")
        self.assertTrue(manifest["all_artifacts_ok"])
        self.assertTrue(manifest["readme_third_person_setup_ok"])


if __name__ == "__main__":
    unittest.main()
