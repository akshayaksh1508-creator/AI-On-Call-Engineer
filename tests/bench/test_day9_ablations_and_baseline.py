"""Unit tests for Day 9 Tasks A1 & A2 (Ablation Flags & Human Baseline).

Verifies:
1. Task A1: `--no-memory`, `--no-code`, `--no-verify` run 3 times on the same faults;
   logs confirm each feature is disabled and per-flag JSON results are saved.
2. Task A2: Human baseline timer sheet has 5 timed incidents for both Person A and
   Person B with start, end, notes, and zero prior ground-truth exposure.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bench.ablations import DEFAULT_ABLATION_FAULTS, run_ablation_suite
from bench.human_baseline import (
    HumanBaselineEntry,
    create_default_human_baseline,
    validate_timer_sheet,
    write_human_baseline_artifacts,
)


class TestDay9AblationsAndHumanBaseline(unittest.TestCase):
    """Test suite for Day 9 Tasks A1 and A2."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_ablation_flags_three_runs_per_flag_logs_and_files_saved(self) -> None:
        """Exit criterion A1: All 3 ablation flags run 3 times on same faults, logs confirm off, files saved."""
        ablation_dir = self.out_dir / "ablations"
        combined = run_ablation_suite(
            fault_ids=DEFAULT_ABLATION_FAULTS,
            repeats=3,
            out_dir=ablation_dir,
        )

        self.assertTrue((ablation_dir / "ablation_summary.json").exists())
        expected_runs = 3 * len(DEFAULT_ABLATION_FAULTS)

        flag_expected_log = {
            "full": "full system enabled",
            "no_memory": "memory retrieval disabled (--no-memory)",
            "no_code": "code-reading tools disabled (--no-code)",
            "no_verify": "sandbox & canary verification disabled (--no-verify)",
        }

        for flag_name, expected_log_substr in flag_expected_log.items():
            flag_file = Path(combined["files"][flag_name])
            self.assertTrue(flag_file.exists(), f"Missing {flag_file}")
            payload = json.loads(flag_file.read_text(encoding="utf-8"))

            self.assertEqual(payload["repeats"], 3)
            self.assertEqual(payload["summary"]["total_runs"], expected_runs)
            self.assertEqual(len(payload["runs"]), expected_runs)

            logs = payload["verification_logs"]
            self.assertEqual(len(logs), expected_runs)
            self.assertTrue(
                all(expected_log_substr in line for line in logs),
                f"Logs for {flag_name} did not confirm disabled feature",
            )

        # Verify ablation behavior deltas make sense
        self.assertGreater(
            combined["flags"]["full"]["fix_success_rate"],
            combined["flags"]["no_code"]["fix_success_rate"],
        )
        self.assertGreater(
            combined["flags"]["no_verify"]["unsafe_rate"],
            combined["flags"]["full"]["unsafe_rate"],
        )

    def test_02_human_baseline_timer_sheet_valid_and_enforces_blind_protocol(self) -> None:
        """Exit criterion A2: Timer sheet with start, end, notes; neither person saw ground truth."""
        entries = create_default_human_baseline()
        payload = write_human_baseline_artifacts(
            entries,
            json_out=self.out_dir / "human_baseline.json",
            md_out=self.out_dir / "human_baseline.md",
        )

        summary = payload["summary"]
        self.assertTrue(summary["valid"], f"Validation errors: {summary['errors']}")
        self.assertEqual(summary["total_entries"], 10)
        self.assertEqual(summary["by_engineer"]["Person A"]["count"], 5)
        self.assertEqual(summary["by_engineer"]["Person B"]["count"], 5)
        self.assertTrue((self.out_dir / "human_baseline.json").exists())
        self.assertTrue((self.out_dir / "human_baseline.md").exists())

        # Negative test: ground truth seen beforehand must fail validation
        bad = list(entries)
        bad[0] = HumanBaselineEntry(
            engineer="Person A",
            fault_id="fault_001_bad_deploy",
            start_time="2026-11-25T10:00:00Z",
            end_time="2026-11-25T10:05:00Z",
            duration_seconds=300.0,
            tools_used=["logs"],
            saw_ground_truth_beforehand=True,
            resolved=True,
            notes="Peeked at ground truth",
        )
        bad_summary = validate_timer_sheet(bad)
        self.assertFalse(bad_summary["valid"])
        self.assertTrue(any("saw_ground_truth_beforehand" in e for e in bad_summary["errors"]))


if __name__ == "__main__":
    unittest.main()
