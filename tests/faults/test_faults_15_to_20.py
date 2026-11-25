"""Unit tests for Faults 15-20 (resource & cross-service) - Day 7 Task A2.

Verifies:
1. All 6 faults (15-20) have valid catalog manifest.json, ground_truth.yaml, and FaultManifest validation.
2. All 6 specs (fault_15.yaml - fault_20.yaml) load via faults.env_faults.load_specs.
3. Each fault reproduces deterministically 3 times in a row and reverts cleanly to healthy state.
4. Ground truth fields match docs/faults.json.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml

from faults.env_faults import load_specs
from faults.manifest import FaultManifest
from faults.repro_15_to_20 import FAULTS_15_TO_20, Fault15To20Harness

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestFaults15To20(unittest.TestCase):
    """Day 7 Task A2 verification for Faults 15 to 20."""

    def setUp(self) -> None:
        self.harness = Fault15To20Harness()
        docs_data = json.loads((REPO_ROOT / "docs" / "faults.json").read_text(encoding="utf-8"))
        fault_list = docs_data["faults"] if isinstance(docs_data, dict) else docs_data
        self.docs_by_id = {f["fault_id"]: f for f in fault_list}

    def test_01_all_six_catalog_manifests_and_ground_truth_valid(self) -> None:
        """Each fault 15-20 has verified ground truth matching docs/faults.json."""
        self.assertEqual(len(FAULTS_15_TO_20), 6)
        for fid, expected in FAULTS_15_TO_20.items():
            cdir = REPO_ROOT / "faults" / "catalog" / fid
            manifest_path = cdir / "manifest.json"
            gt_path = cdir / "ground_truth.yaml"
            self.assertTrue(manifest_path.exists(), f"Missing manifest.json for {fid}")
            self.assertTrue(gt_path.exists(), f"Missing ground_truth.yaml for {fid}")

            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            gt_data = yaml.safe_load(gt_path.read_text(encoding="utf-8"))

            # Validate against FaultManifest contract
            m = FaultManifest(**manifest_data)
            g = FaultManifest(**gt_data)
            self.assertEqual(m.fault_id, fid)
            self.assertEqual(g.fault_id, fid)
            self.assertIn(m.category, ("resource", "cross_service"))
            self.assertEqual(m.root_cause, expected["root_cause"])

            # Verify parity with docs/faults.json
            doc = self.docs_by_id[fid]
            self.assertEqual(m.category, doc["category"])
            self.assertEqual(m.target_service, doc["target_service"])
            self.assertEqual(m.root_cause, doc["root_cause"])
            self.assertEqual(m.risk_tier, doc["risk_tier"])

    def test_02_env_fault_specs_15_to_20_load_cleanly(self) -> None:
        """fault_15.yaml through fault_20.yaml load via load_specs."""
        specs = load_specs(REPO_ROOT / "faults" / "specs_15_to_20")
        for idx in range(15, 21):
            spec_id = f"fault_{idx}"
            self.assertIn(spec_id, specs, f"Missing spec {spec_id}.yaml")
            self.assertIn(specs[spec_id].category, ("resource", "cross_service"))

    def test_03_each_fault_reproduces_three_times_in_a_row(self) -> None:
        """Exit criterion: Each of faults 15-20 reproduces 3 times in a row cleanly."""
        for fid in FAULTS_15_TO_20:
            with self.subTest(fault_id=fid):
                for attempt in range(1, 4):
                    # Clean before injection
                    clean_before = self.harness.reproduce(fid)
                    self.assertFalse(clean_before["reproduced"], f"{fid} attempt {attempt}: not clean before")

                    # Inject & reproduce
                    self.harness.inject(fid)
                    repro = self.harness.reproduce(fid)
                    self.assertTrue(repro["reproduced"], f"{fid} attempt {attempt}: failed to reproduce")
                    self.assertIsNotNone(repro["error"], f"{fid} attempt {attempt}: missing error detail")

                    # Revert & confirm healthy
                    self.harness.revert(fid)
                    clean_after = self.harness.reproduce(fid)
                    self.assertFalse(clean_after["reproduced"], f"{fid} attempt {attempt}: failed to revert")


if __name__ == "__main__":
    unittest.main()
