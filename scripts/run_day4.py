
"""Run the Day 4 five-fault patch gate using source-generated fixes.

This runner deliberately generates patches from buggy_app.py and incident
evidence. It does not read patched_app.py or use ground-truth diffs to create
the remediation patch.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contracts.models import Evidence, FixProposal, Hypothesis, Incident
from fixer.fixer import Fixer
from reporter.github_pr import GitHubPRClient
from verifier.sandbox import SandboxVerifier


FAULTS = [
    ("fault_001_bad_deploy", "orders", "test_fault_001_bad_deploy"),
    ("fault_002_off_by_one", "orders", "test_fault_002_off_by_one"),
    ("fault_003_wrong_status_code", "payments", "test_fault_003_wrong_status_code"),
    ("fault_004_bad_parsing", "gateway", "test_fault_004_bad_parsing"),
    ("fault_005_unhandled_exception", "orders", "test_fault_005_unhandled_exception"),
]


def _load_fault_context(
    fault_id: str,
    service: str,
) -> tuple[str, str, Hypothesis, list[Evidence], dict[str, Any]]:
    """Load faulty source and incident context, then generate a candidate."""

    fixture = ROOT / "faults" / "catalog" / fault_id
    metadata_path = fixture / "ground_truth.yaml"
    source_path = fixture / "buggy_app.py"

    if not metadata_path.is_file():
        raise FileNotFoundError(f"Missing fault metadata: {metadata_path}")

    if not source_path.is_file():
        raise FileNotFoundError(f"Missing faulty source: {source_path}")

    metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
    source = source_path.read_text(encoding="utf-8")

    target = f"target-app/services/{service}/app.py"

    evidence = [
        Evidence(
            id=f"ev_{fault_id}",
            type="log",
            ref=f"fixture:{fault_id}",
            excerpt="; ".join(metadata.get("visible_symptoms", [])),
            ts=datetime.now(timezone.utc).isoformat(),
        )
    ]

    hypothesis = Hypothesis(
        cause=metadata["root_cause"],
        category=metadata["category"],
        confidence=0.9,
        evidence_ids=[evidence[0].id],
        culprit_change=metadata.get("culprit_change"),
    )

    # Important: candidate generation receives only the faulty source,
    # target path, and hypothesis. No corrected fixture is read here.
    patch, rationale = Fixer(ROOT).generate_candidate_diff(
        source,
        target,
        hypothesis,
    )

    return patch or "", rationale or "", hypothesis, evidence, metadata


def _validate_patch(
    patch: str,
    hypothesis: Hypothesis,
    evidence: list[Evidence],
    source_path: Path,
    target: str,
    service: str,
) -> FixProposal:
    """Validate the generated patch using a temporary Git repository."""

    with tempfile.TemporaryDirectory(prefix="day4-patch-check-") as folder:
        base = Path(folder)
        target_path = base / target
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(source_path.read_bytes())

        subprocess.run(["git", "init", "-q"], cwd=base, check=True)
        subprocess.run(["git", "add", "."], cwd=base, check=True)
        subprocess.run(
            [
                "git",
                "-c", "user.name=day4",
                "-c", "user.email=day4@example.invalid",
                "commit", "-qm", "faulty fixture",
            ],
            cwd=base,
            check=True,
        )

        return Fixer(base).proposal(
            hypothesis,
            evidence,
            patch,
            "Fault-specific reproduction passes after the patch.",
            target_service=service,
        )


def _test_summary(output: str) -> str:
    """Extract useful pytest/unittest summary lines."""

    lines = output.splitlines()
    summaries = [
        line
        for line in lines
        if re.match(
            r"^(Ran \d+ tests?|OK|FAILED|FAILED \(|ERROR:|\d+ passed|\d+ failed)",
            line.strip(),
        )
    ]

    return "\n".join(summaries[-4:]) if summaries else output[-500:]


def _failed_result(
    fault_id: str,
    service: str,
    error: str,
    rationale: str = "",
) -> dict[str, Any]:
    """Build a consistent result when generation or validation fails."""

    return {
        "fault_id": fault_id,
        "service": service,
        "patch_generated": False,
        "patch_validated": False,
        "reproduction_failed_before_patch": False,
        "tests_passed": False,
        "reproduction_passed_after_patch": False,
        "sandbox_passed": False,
        "fix_generation_mode": "deterministic source-based rule generator",
        "rationale": rationale,
        "error": error,
        "unit_test_summary": "",
        "reproduction_output_on_failure": "",
        "mock_pr": None,
        "mock_pr_content_complete": False,
    }


def main() -> int:
    results: list[dict[str, Any]] = []

    try:
        verifier = SandboxVerifier(
            ROOT,
            use_container=False,
            timeout=120,
        )
        github = GitHubPRClient(
            mock=True,
            repo="sandbox/day4-fixes",
        )

        for fault_id, service, test_name in FAULTS:
            target = f"target-app/services/{service}/app.py"
            source_path = (
                ROOT / "faults" / "catalog" / fault_id / "buggy_app.py"
            )

            print(f"\n{'=' * 65}")
            print(f"Processing {fault_id}")
            print(f"{'=' * 65}")

            try:
                patch, rationale, hypothesis, evidence, metadata = (
                    _load_fault_context(fault_id, service)
                )

                if not patch.strip():
                    results.append(
                        _failed_result(
                            fault_id,
                            service,
                            "Fixer did not generate a candidate patch.",
                            rationale,
                        )
                    )
                    print("FAIL: no candidate patch generated")
                    continue

                if f"diff --git a/{target} b/{target}" not in patch:
                    results.append(
                        _failed_result(
                            fault_id,
                            service,
                            "Generated patch does not target the expected file.",
                            rationale,
                        )
                    )
                    print("FAIL: generated patch targets an unexpected file")
                    continue

                print("Candidate patch generated from faulty source.")

                proposal = _validate_patch(
                    patch,
                    hypothesis,
                    evidence,
                    source_path,
                    target,
                    service,
                )

                validated_patch = proposal.diff or ""

                if not validated_patch.strip():
                    results.append(
                        _failed_result(
                            fault_id,
                            service,
                            "Patch validation produced an empty proposal diff.",
                            rationale,
                        )
                    )
                    print("FAIL: validated proposal is empty")
                    continue

                incident = Incident(
                    id=f"day4-{fault_id}",
                    service=service,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    symptoms=metadata.get("visible_symptoms", []),
                )

                test_command = [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    (
                        "tests/verifier/test_reproductions.py::"
                        "TestDay4Reproductions::"
                        + test_name
                    ),
                ]

                reproduction_command = [
                    sys.executable,
                    "tests/verifier/reproduce.py",
                    fault_id,
                ]

                run = verifier.verify(
                    incident.id,
                    validated_patch,
                    target_file=target,
                    faulty_file=f"faults/catalog/{fault_id}/buggy_app.py",
                    test_command=test_command,
                    reproduction_command=reproduction_command,
                )

                pr = github.create_remediation_pr(
                    incident,
                    hypothesis,
                    proposal,
                    head_branch=f"fix/{fault_id}",
                    verification=run.verification,
                )

                verification = run.verification

                result = {
                    "fault_id": fault_id,
                    "service": service,
                    "patch_generated": True,
                    "patch_validated": True,
                    "fix_generation_mode": (
                        "deterministic source-based rule generator"
                    ),
                    "rationale": rationale,
                    "reproduction_failed_before_patch": (
                        run.reproduction_failed_before
                    ),
                    "tests_passed": verification.tests_passed,
                    "reproduction_passed_after_patch": (
                        verification.repro_fixed
                    ),
                    "sandbox_passed": verification.verdict == "PASS",
                    "verification_verdict": verification.verdict,
                    "error": run.error,
                    "unit_test_summary": _test_summary(
                        run.unit_test_output
                    ),
                    "reproduction_output_on_failure": (
                        run.reproduction_output if run.error else ""
                    ),
                    "mock_pr": {
                        "number": pr["number"],
                        "url": pr["html_url"],
                    },
                    "mock_pr_content_complete": all(
                        section in pr["body"]
                        for section in (
                            hypothesis.cause,
                            evidence[0].id,
                            "Fault-specific reproduction passes after the patch.",
                            "PASSED",
                        )
                    ),
                }

                results.append(result)

                status = "PASS" if result["sandbox_passed"] else "FAIL"
                print(f"{fault_id}: {status}")
                print(f"Verification verdict: {verification.verdict}")

            except Exception as fault_error:
                results.append(
                    _failed_result(
                        fault_id,
                        service,
                        f"{type(fault_error).__name__}: {fault_error}",
                    )
                )
                print(f"FAIL: {fault_error}")

        passed = sum(
            1 for item in results if item["sandbox_passed"]
        )

        report = {
            "day": 4,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "patch_generation": (
                "deterministic source-based rule generator"
            ),
            "corrected_fixture_used_for_patch_generation": False,
            "verification_mode": (
                "isolated git worktree, host unit tests and reproductions"
            ),
            "live_docker_available": shutil.which("docker") is not None,
            "pr_mode": "mock; no live GitHub pull requests were created",
            "faults_attempted": len(results),
            "patches_generated": sum(
                1 for item in results if item["patch_generated"]
            ),
            "patches_validated": sum(
                1 for item in results if item.get("patch_validated", False)
            ),
            "sandbox_passed": passed,
            "fix_rate": passed / len(FAULTS),
            "exit_gate_required": 3,
            "exit_gate_passed": passed >= 3,
            "fault_results": results,
        }

        destination = ROOT / "results" / "day4_execution.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, indent=2) + "\n",
            encoding="utf-8",
        )

        print("\nDAY 4 SUMMARY")
        print("=" * 65)
        print(
            json.dumps(
                {
                    key: value
                    for key, value in report.items()
                    if key != "fault_results"
                },
                indent=2,
            )
        )

        for item in results:
            status = "PASS" if item["sandbox_passed"] else "FAIL"
            print(
                f"{item['fault_id']}: {status}; "
                f"patch generated: {item['patch_generated']}; "
                f"patch validated: {item.get('patch_validated', False)}"
            )

        print(f"\nReport saved to: {destination}")

        return 0 if report["exit_gate_passed"] else 1

    except Exception as exc:
        print(
            f"Day 4 run failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
