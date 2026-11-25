"""Unit tests for 5-Incident Memory Experiment (Day 9 Task B3).

Verifies:
  - 5 repeated incidents run both with and without memory.
  - Steps and duration_seconds are recorded per run.
  - Exact delta is reported.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memory import run_memory_experiment


class TestMemoryExperiment(unittest.TestCase):
    """Test suite for Day 9 Task B3 Memory Experiment."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.out_file = Path(self.tmp.name) / "memory_experiment.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_01_five_repeated_incidents_with_and_without_memory(self) -> None:
        """Exit criterion B3: Steps and time per run recorded for 5 incidents; delta reported."""
        report = run_memory_experiment(out_path=self.out_file)

        self.assertTrue(self.out_file.exists())
        loaded = json.loads(self.out_file.read_text(encoding="utf-8"))

        self.assertEqual(loaded["incident_count"], 5)
        self.assertEqual(len(loaded["without_memory"]["runs"]), 5)
        self.assertEqual(len(loaded["with_memory"]["runs"]), 5)

        for r in loaded["without_memory"]["runs"]:
            self.assertGreater(r["steps"], 0)
            self.assertGreater(r["duration_seconds"], 0.0)
            self.assertFalse(r["memory_hit"])

        for r in loaded["with_memory"]["runs"]:
            self.assertGreater(r["steps"], 0)
            self.assertGreater(r["duration_seconds"], 0.0)
            self.assertTrue(r["memory_hit"])

        self.assertIn("steps_saved_per_run", loaded["delta"])
        self.assertIn("time_saved_seconds_per_run", loaded["delta"])
        self.assertGreater(loaded["delta"]["steps_saved_per_run"], 0)


if __name__ == "__main__":
    unittest.main()
