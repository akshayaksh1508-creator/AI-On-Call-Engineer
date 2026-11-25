import re
import unittest
from pathlib import Path

from pitch.cross_check import cross_check_deck_against_final_json

REPO_ROOT = Path(__file__).resolve().parents[2]
DECK_FINAL_PATH = REPO_ROOT / "pitch" / "deck_final.md"
QA_BANK_PATH = REPO_ROOT / "pitch" / "qa_bank.md"
CRITIQUE_PATH = REPO_ROOT / "pitch" / "dry_run_critique.md"


class TestDay11B1ToB3(unittest.TestCase):
    def test_b1_cross_check_deck_against_final_json(self):
        result = cross_check_deck_against_final_json()
        self.assertTrue(result["passed"], f"Deck cross-check failed: {result['mismatches']}")
        self.assertEqual(result["mismatches"], [])
        self.assertGreaterEqual(len(result["checked_fields"]), 10)

        deck_text = DECK_FINAL_PATH.read_text(encoding="utf-8")
        self.assertIn("Failure Analysis", deck_text)

    def test_b2_qa_bank_topics_count_and_under_30s(self):
        text = QA_BANK_PATH.read_text(encoding="utf-8")
        required_topics = ["safety", "hallucination", "cost", "scaling", "competitors"]
        for topic in required_topics:
            matches = re.findall(rf"### Q\d+\s+`?\[{topic}\]`?:", text)
            self.assertEqual(
                len(matches),
                2,
                f"Expected 2 questions for topic '{topic}', found {len(matches)}",
            )

        answers = re.findall(
            r"\*\*Answer:\*\*\s*\n(.*?)(?=\n### |\n---|\Z)",
            text,
            flags=re.DOTALL,
        )
        self.assertEqual(len(answers), 10, f"Expected 10 answers, found {len(answers)}")
        for idx, ans in enumerate(answers, start=1):
            words = ans.strip().split()
            self.assertLessEqual(
                len(words),
                70,
                f"Q{idx} answer has {len(words)} words (> 70 word ~30s spoken limit)",
            )

    def test_b3_dry_run_critique_has_three_points_and_fixes(self):
        text = CRITIQUE_PATH.read_text(encoding="utf-8")
        critiques = re.findall(r"### Critique \d+", text)
        self.assertEqual(len(critiques), 3, f"Expected 3 critique points, found {len(critiques)}")
        fixes = re.findall(r"\*\*Fix Applied:\*\*", text)
        self.assertEqual(len(fixes), 3, f"Expected 3 applied fixes, found {len(fixes)}")


if __name__ == "__main__":
    unittest.main()
