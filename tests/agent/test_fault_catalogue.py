"""Unit Tests Validating the 25-Fault Catalogue (Task B2).

Verifies Section 8 & Section 14 criteria:
1. docs/faults.md exists and documents all 25 faults.
2. docs/faults.json parses with 100% schema compliance.
3. Category mix is exactly: 8 code, 4 config, 4 resource, 4 cross-service, 5 stretch.
4. Every fault has unambiguous ground truth: root cause, culprit change, visible symptoms, expected fix, and risk tier.
"""

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs"
FAULTS_MD = DOCS_DIR / "faults.md"
FAULTS_JSON = DOCS_DIR / "faults.json"


class TestFaultCatalogue(unittest.TestCase):
    """Test suite validating fault catalogue completeness and distribution."""

    def test_01_catalogue_files_exist(self):
        """docs/faults.md and docs/faults.json must both exist."""
        self.assertTrue(FAULTS_MD.exists(), "docs/faults.md is required")
        self.assertTrue(FAULTS_JSON.exists(), "docs/faults.json is required")

    def test_02_fault_count_and_uniqueness(self):
        """Catalogue must contain exactly 25 unique faults."""
        with open(FAULTS_JSON, "r", encoding="utf-8") as f:
            faults = json.load(f)

        self.assertEqual(len(faults), 25, f"Expected exactly 25 faults, found {len(faults)}")

        ids = [f["fault_id"] for f in faults]
        self.assertEqual(len(ids), len(set(ids)), "Fault IDs must be unique")

        # Validate ID naming pattern fault_001 to fault_025
        pattern = re.compile(r"^fault_\d{3}_[a-z0-9_]+$")
        for fid in ids:
            self.assertTrue(pattern.match(fid), f"Fault ID '{fid}' does not match pattern fault_XXX_name")

    def test_03_category_distribution_mix(self):
        """Category mix must match: 8 code, 4 config, 4 resource, 4 cross-service, 5 stretch."""
        with open(FAULTS_JSON, "r", encoding="utf-8") as f:
            faults = json.load(f)

        category_counts = {}
        for f in faults:
            cat = f["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1

        self.assertEqual(category_counts.get("code", 0), 8, "Must have exactly 8 code faults")
        self.assertEqual(category_counts.get("config", 0), 4, "Must have exactly 4 config faults")
        self.assertEqual(category_counts.get("resource", 0), 4, "Must have exactly 4 resource faults")
        self.assertEqual(category_counts.get("cross_service", 0), 4, "Must have exactly 4 cross-service faults")
        self.assertEqual(category_counts.get("stretch", 0), 5, "Must have exactly 5 stretch faults")

    def test_04_fault_fields_completeness(self):
        """Every fault must specify unambiguous ground-truth fields."""
        with open(FAULTS_JSON, "r", encoding="utf-8") as f:
            faults = json.load(f)

        valid_categories = {"code", "config", "resource", "cross_service", "stretch"}
        valid_services = {"orders", "payments", "gateway"}
        valid_difficulties = {"easy", "medium", "hard"}
        valid_fix_types = {"patch", "config", "rollback"}
        valid_tiers = {"T0", "T1", "T2", "T3"}

        for f in faults:
            fid = f["fault_id"]
            self.assertTrue(f["title"], f"{fid}: Title must not be empty")
            self.assertIn(f["category"], valid_categories, f"{fid}: Invalid category")
            self.assertIn(f["target_service"], valid_services, f"{fid}: Invalid target service")
            self.assertIn(f["difficulty"], valid_difficulties, f"{fid}: Invalid difficulty")
            self.assertTrue(f["culprit_change"], f"{fid}: Culprit change must not be empty")
            self.assertTrue(f["root_cause"], f"{fid}: Root cause must not be empty")
            self.assertGreater(len(f["visible_symptoms"]), 0, f"{fid}: Must have visible symptoms")
            self.assertIn(f["expected_fix_type"], valid_fix_types, f"{fid}: Invalid fix type")
            self.assertIn(f["risk_tier"], valid_tiers, f"{fid}: Invalid risk tier")

    def test_05_markdown_documentation_coverage(self):
        """docs/faults.md must mention all 25 fault IDs."""
        with open(FAULTS_JSON, "r", encoding="utf-8") as f:
            faults = json.load(f)

        md_content = FAULTS_MD.read_text(encoding="utf-8")
        for f in faults:
            fid = f["fault_id"]
            self.assertIn(fid, md_content, f"Markdown documentation missing section for {fid}")


if __name__ == "__main__":
    unittest.main()
