"""Unit tests for Day 10 Tasks B1-B3 (Business Case, Deck/Demo Script, Safety Demo).

Verifies:
1. Task B1: Business case covers customer, pain, pricing, trust ladder, moat, measured cost,
   and labels market sizes as [ASSUMPTION].
2. Task B2: Deck draft and 3-minute demo script exist with timed segments <= 3:00 (180s).
3. Task B3: Safety demo triggers T3 escalation, auto-rollback, and kill switch live.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from pitch.safety_demo import run_safety_demo_rehearsal

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestDay10TasksB1ToB3(unittest.TestCase):
    """Test suite for Day 10 Person B tasks (B1-B3)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_business_case_traces_to_results_and_labels_assumptions(self) -> None:
        """Exit criterion B1: All required sections present, numbers traced, market sizes labelled [ASSUMPTION]."""
        bc_path = REPO_ROOT / "pitch" / "business_case.md"
        self.assertTrue(bc_path.exists())
        text = bc_path.read_text(encoding="utf-8")

        for section in ("Target Customer", "Pain", "Pricing", "Trust Ladder", "Moat", "Market Sizing"):
            self.assertIn(section, text)

        self.assertIn("[ASSUMPTION]", text)
        self.assertIn("results/v2_improved.json", text)
        self.assertIn("results/human_baseline.json", text)
        self.assertIn("$0.0147", text)

    def test_02_deck_and_three_minute_demo_script_within_budget(self) -> None:
        """Exit criterion B2: Deck draft and timed 3:00 demo script <= 180s."""
        deck_path = REPO_ROOT / "pitch" / "deck_draft.md"
        script_path = REPO_ROOT / "pitch" / "demo_script_3min.md"
        self.assertTrue(deck_path.exists())
        self.assertTrue(script_path.exists())

        script_text = script_path.read_text(encoding="utf-8")
        durations = [int(m) for m in re.findall(r"\|\s*`(\d+)s`\s*\|", script_text)]
        self.assertGreaterEqual(len(durations), 4)
        self.assertLessEqual(sum(durations), 180, f"Demo script {sum(durations)}s exceeds 3:00 (180s)")

    def test_03_safety_demo_triggers_t3_rollback_and_kill_switch_live(self) -> None:
        """Exit criterion B3: T3 escalation, auto-rollback, and kill switch all trigger live."""
        res = run_safety_demo_rehearsal(
            repo_root=REPO_ROOT,
            out_path=self.out_dir / "safety_demo.json",
        )
        self.assertTrue(res["t3_escalation"]["triggered"])
        self.assertTrue(res["auto_rollback"]["triggered"])
        self.assertTrue(res["kill_switch"]["triggered"])
        self.assertTrue(res["all_safety_features_verified"])


if __name__ == "__main__":
    unittest.main()
