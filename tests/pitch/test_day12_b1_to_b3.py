import re
import unittest
from pathlib import Path

from pitch.section12_checklist import run_section12_checklist

REPO_ROOT = Path(__file__).resolve().parents[2]
REHEARSAL_LOG_PATH = REPO_ROOT / "pitch" / "rehearsal_log.md"
CHOREOGRAPHY_PATH = REPO_ROOT / "pitch" / "demo_choreography.md"


class TestDay12B1ToB3(unittest.TestCase):
    def test_b1_three_rehearsals_within_time_and_fallback_under_20s(self):
        text = REHEARSAL_LOG_PATH.read_text(encoding="utf-8")
        runs = re.findall(r"\|\s*\*\*Run \d+\*\*\s*\|", text)
        self.assertEqual(len(runs), 3, f"Expected 3 rehearsal runs, found {len(runs)}")

        times = [int(t) for t in re.findall(r"\|\s*`(\d+)s`\s*\(`2m \d+s`\)\s*\|", text)]
        self.assertEqual(len(times), 3)
        for t in times:
            self.assertLessEqual(t, 180)

        fallback_switches = [int(s) for s in re.findall(r"\|\s*`(\d+)s`\s*\|\s*Yes \(`\d+s < 20s`\)\s*\|", text)]
        self.assertGreaterEqual(len(fallback_switches), 1)
        for sw in fallback_switches:
            self.assertLess(sw, 20)

    def test_b2_demo_choreography_run_sheet_and_solo_capable(self):
        text = CHOREOGRAPHY_PATH.read_text(encoding="utf-8")
        self.assertIn("Who Types", text)
        self.assertIn("Who Speaks", text)
        self.assertIn("Who Handles Judge Curveball", text)
        self.assertIn("If Person A runs solo", text)
        self.assertIn("If Person B runs solo", text)

    def test_b3_section12_checklist_all_14_items_ticked(self):
        report = run_section12_checklist()
        self.assertEqual(report["total_items"], 14)
        self.assertEqual(report["passed_items"], 14, f"Failed items: {[i for i in report['items'] if not i['passed']]}")
        self.assertTrue(report["all_passed"])


if __name__ == "__main__":
    unittest.main()
