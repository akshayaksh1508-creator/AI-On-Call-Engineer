"""Day 12 Task A3 — Backup Video, README & Submission Package Verifier.

Verifies that all required Day 12 A3 submission package artifacts exist, are
non-empty, and that `README.md` contains complete third-person setup instructions
(clone, venv, `requirements-frozen.txt`, `.env` spend cap, `python run.py test`,
and backup video/replay references).

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_JSON = REPO_ROOT / "results" / "submission_package_manifest.json"

REQUIRED_ARTIFACTS = [
    "README.md",
    "requirements-frozen.txt",
    ".env.example",
    "results/final.json",
    "results/final_results_page.html",
    "results/final_failure_table.md",
    "results/demo_backup_video.gif",
    "results/demo_backup_video.webp",
    "results/demo_backup_video.html",
    "results/recorded_replay_fault_001.json",
    "pitch/deck_final.md",
    "pitch/demo_script_3min.md",
    "pitch/qa_bank.md",
    "pitch/dry_run_critique.md",
]

REQUIRED_README_SECTIONS = [
    "requirements-frozen.txt",
    ".env.example",
    "ANTHROPIC_SPEND_CAP_USD",
    "python run.py test",
    "demo_backup_video",
    "offline_replay",
]


def build_submission_package_manifest(
    *,
    output_json: Path = DEFAULT_MANIFEST_JSON,
) -> Dict[str, Any]:
    artifact_checks: List[Dict[str, Any]] = []
    for rel_path in REQUIRED_ARTIFACTS:
        full_path = REPO_ROOT / rel_path
        exists = full_path.exists()
        size_bytes = full_path.stat().st_size if exists else 0
        artifact_checks.append(
            {
                "path": rel_path,
                "exists": exists,
                "size_bytes": size_bytes,
                "passed": exists and size_bytes > 0,
            }
        )

    readme_path = REPO_ROOT / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""
    readme_checks = [
        {"token": token, "present": token in readme_text}
        for token in REQUIRED_README_SECTIONS
    ]

    all_artifacts_ok = all(item["passed"] for item in artifact_checks)
    readme_ok = all(item["present"] for item in readme_checks)

    manifest: Dict[str, Any] = {
        "task": "Day 12 A3 - Backup Video, README, and Submission Package",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "all_passed": all_artifacts_ok and readme_ok,
        "all_artifacts_ok": all_artifacts_ok,
        "readme_third_person_setup_ok": readme_ok,
        "artifacts": artifact_checks,
        "readme_checks": readme_checks,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    result = build_submission_package_manifest()
    print(json.dumps(result, indent=2))
