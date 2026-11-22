"""Unit tests for Monorepo Layout, CODEOWNERS, and Foundation Scaffold (Task A1)."""

import os
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


class TestMonorepoLayout(unittest.TestCase):
    """Verify monorepo structure conforms to Architecture Section 5."""

    EXPECTED_COMPONENTS_A = [
        "target-app",
        "infra",
        "faults",
        "detector",
        "platform_api",
        "deployer",
        "verifier",
        "bench",
    ]

    EXPECTED_COMPONENTS_B = [
        "agent",
        "fixer",
        "memory",
        "safety",
        "reporter",
        "dashboard",
        "pitch",
        "orchestrator",
    ]

    SHARED_COMPONENTS = ["contracts"]

    def test_all_component_directories_exist(self):
        """Verify that every component folder from Section 5 exists."""
        all_components = self.SHARED_COMPONENTS + self.EXPECTED_COMPONENTS_A + self.EXPECTED_COMPONENTS_B
        for comp in all_components:
            comp_path = ROOT_DIR / comp
            self.assertTrue(
                comp_path.is_dir(),
                f"Required component directory missing: {comp}"
            )

    def test_all_component_tests_directories_exist(self):
        """Verify that every component has a corresponding test folder in /tests."""
        all_components = self.SHARED_COMPONENTS + self.EXPECTED_COMPONENTS_A + self.EXPECTED_COMPONENTS_B
        for comp in all_components:
            test_path = ROOT_DIR / "tests" / comp
            self.assertTrue(
                test_path.is_dir(),
                f"Required test directory missing: tests/{comp}"
            )

    def test_env_example_contains_required_keys(self):
        """Verify .env.example contains essential configuration keys."""
        env_example = ROOT_DIR / ".env.example"
        self.assertTrue(env_example.is_file(), ".env.example must exist in root")
        
        content = env_example.read_text(encoding="utf-8")
        required_keys = [
            "ANTHROPIC_API_KEY",
            "GATEWAY_PORT",
            "ORDERS_PORT",
            "PAYMENTS_PORT",
            "POSTGRES_USER",
            "PLATFORM_API_PORT",
            "SAFETY_KILL_SWITCH",
            "CONFIDENCE_THRESHOLD_T1",
            "CONFIDENCE_THRESHOLD_T2",
            "SLACK_WEBHOOK_URL",
        ]
        for key in required_keys:
            self.assertIn(key, content, f"Key '{key}' missing from .env.example")

    def test_gitignore_protects_secrets(self):
        """Verify that .gitignore properly ignores .env and cache files."""
        gitignore = ROOT_DIR / ".gitignore"
        self.assertTrue(gitignore.is_file(), ".gitignore must exist in root")
        
        content = gitignore.read_text(encoding="utf-8")
        self.assertIn(".env", content, ".env must be ignored")
        self.assertIn("__pycache__", content, "__pycache__ must be ignored")

    def test_makefile_has_required_targets(self):
        """Verify Makefile defines up, test, demo, and reset targets."""
        makefile = ROOT_DIR / "Makefile"
        self.assertTrue(makefile.is_file(), "Makefile must exist in root")
        
        content = makefile.read_text(encoding="utf-8")
        for target in ["up:", "test:", "demo:", "reset:"]:
            self.assertIn(target, content, f"Target '{target}' missing from Makefile")

    def test_ci_workflow_exists(self):
        """Verify GitHub Actions CI workflow exists."""
        ci_workflow = ROOT_DIR / ".github" / "workflows" / "ci.yml"
        self.assertTrue(ci_workflow.is_file(), ".github/workflows/ci.yml must exist")


class TestCodeownersPolicy(unittest.TestCase):
    """Verify CODEOWNERS enforces strict directory ownership."""

    def setUp(self):
        self.codeowners_file = ROOT_DIR / ".github" / "CODEOWNERS"
        self.assertTrue(self.codeowners_file.is_file(), ".github/CODEOWNERS must exist")
        self.content = self.codeowners_file.read_text(encoding="utf-8")
        
        # Build mapping of path -> list of owners
        self.ownership = {}
        for line in self.content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                path = parts[0].strip("/")
                owners = parts[1:]
                self.ownership[path] = owners

    def test_contracts_requires_dual_approval(self):
        """Contracts must require approval from BOTH Person A and Person B."""
        contracts_owners = self.ownership.get("contracts", [])
        self.assertIn("@person-a", contracts_owners)
        self.assertIn("@person-b", contracts_owners)

    def test_person_a_directories(self):
        """Verify Person A owns all systems and proof directories."""
        for comp in TestMonorepoLayout.EXPECTED_COMPONENTS_A:
            owners = self.ownership.get(comp, [])
            self.assertIn("@person-a", owners, f"/{comp}/ must be assigned to @person-a")
            self.assertNotIn("@person-b", owners, f"/{comp}/ should not be assigned to @person-b")

    def test_person_b_directories(self):
        """Verify Person B owns all brain and trust directories."""
        for comp in TestMonorepoLayout.EXPECTED_COMPONENTS_B:
            owners = self.ownership.get(comp, [])
            self.assertIn("@person-b", owners, f"/{comp}/ must be assigned to @person-b")
            self.assertNotIn("@person-a", owners, f"/{comp}/ should not be assigned to @person-a")


if __name__ == "__main__":
    unittest.main()
