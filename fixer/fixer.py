"""Validate and select small, evidence-backed remediation proposals."""

from __future__ import annotations

import re
import subprocess
import difflib
import tempfile
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

from contracts.models import Evidence, FixProposal, Hypothesis


class FixValidationError(ValueError):
    """Raised when a proposed patch is unsafe or cannot apply cleanly."""


_GIT_DIFF_PATHS = re.compile(r"^diff --git a/(.+) b/(.+)$")


def _paths_from_diff(diff: str) -> list[str]:
    paths: list[str] = []
    for line in diff.splitlines():
        match = _GIT_DIFF_PATHS.match(line)
        if not match:
            continue
        path = match.group(2)
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or "\\" in path:
            raise FixValidationError(f"Unsafe patch path: {path}")
        paths.append(path)
    if not paths:
        raise FixValidationError("Patch contains no file headers")
    return list(dict.fromkeys(paths))


class Fixer:
    """Validate unified diffs before they reach the isolated verifier."""

    def __init__(
        self,
        repo_root: str | Path,
        allowed_paths: Iterable[str] = ("target-app/",),
        max_files: int = 1,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.allowed_paths = tuple(allowed_paths)
        self.max_files = max_files

    @staticmethod
    def generate_unified_diff(before: str, after: str, target_file: str) -> str:
        """Build a minimal unified diff from the faulty and corrected file contents."""
        path = PurePosixPath(target_file)
        if path.is_absolute() or ".." in path.parts or "\\" in target_file:
            raise FixValidationError(f"Unsafe patch path: {target_file}")
        body = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{target_file}",
                tofile=f"b/{target_file}",
            )
        )
        if not body:
            return ""
        return f"diff --git a/{target_file} b/{target_file}\n{body}"

    def validate_diff(
        self,
        diff: str,
        hypothesis: Hypothesis,
        evidence: Iterable[Evidence],
    ) -> str:
        """Check cited evidence, path scope, patch size, and git applicability."""
        clean_diff = diff.rstrip("\r\n")
        if not clean_diff.strip():
            raise FixValidationError("Patch is empty")
        evidence_by_id = {item.id for item in evidence}
        if not hypothesis.evidence_ids:
            raise FixValidationError("Cannot propose a patch without cited evidence")
        missing = set(hypothesis.evidence_ids) - evidence_by_id
        if missing:
            raise FixValidationError(f"Hypothesis cites unknown evidence IDs: {sorted(missing)}")

        paths = _paths_from_diff(clean_diff)
        if len(paths) > self.max_files:
            raise FixValidationError(f"Patch touches {len(paths)} files; maximum is {self.max_files}")
        for path in paths:
            if not any(path.startswith(prefix) for prefix in self.allowed_paths):
                raise FixValidationError(f"Patch path is outside the allowlist: {path}")
            target = (self.repo_root / path).resolve()
            if self.repo_root not in target.parents:
                raise FixValidationError(f"Patch path escapes repository: {path}")

        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".diff", delete=False) as stream:
            patch_file = Path(stream.name)
            stream.write(clean_diff + "\n")
        try:
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout, tempfile.TemporaryFile(
                mode="w+t", encoding="utf-8"
            ) as stderr:
                result = subprocess.run(
                    ["git", "apply", "--check", str(patch_file)],
                    cwd=self.repo_root, stdin=subprocess.DEVNULL,
                    stdout=stdout, stderr=stderr, timeout=10, check=False,
                )
                stdout.seek(0)
                stderr.seek(0)
                output = stderr.read() or stdout.read()
        finally:
            patch_file.unlink(missing_ok=True)
        if result.returncode:
            reason = output.strip() or f"git apply --check exit {result.returncode}"
            raise FixValidationError(f"Patch does not apply: {reason}")
        return clean_diff + "\n"

    def proposal(
        self,
        hypothesis: Hypothesis,
        evidence: Iterable[Evidence],
        diff: str,
        expected_metric_effect: str,
        *,
        recent_deploy: bool = False,
        clean_revert: bool = False,
        config_fault: bool = False,
        config_diff: Optional[str] = None,
        target_service: Optional[str] = None,
    ) -> FixProposal:
        """Choose a remediation type and return its validated proposal."""
        kind = select_fix_type(
            hypothesis,
            recent_deploy=recent_deploy,
            clean_revert=clean_revert,
            config_fault=config_fault,
        )
        selected_diff = diff
        if kind == "config":
            selected_diff = config_diff or diff
        if kind == "patch":
            selected_diff = self.validate_diff(selected_diff, hypothesis, evidence)
        else:
            selected_diff = ""
        return FixProposal(
            type=kind,
            diff=selected_diff,
            risk_tier="T1" if kind in {"rollback", "config"} else "T2",
            rationale=(
                "Revert the recent culprit deployment because a clean rollback is available."
                if kind == "rollback"
                else "Revert the implicated configuration change."
                if kind == "config"
                else hypothesis.cause
            ),
            expected_metric_effect=expected_metric_effect,
            target_service=target_service or "orders",
        )


def select_fix_type(
    hypothesis: Hypothesis,
    *,
    recent_deploy: bool = False,
    clean_revert: bool = False,
    config_fault: bool = False,
) -> str:
    """Apply Day 4's deterministic rollback/config/patch selection rule."""
    if config_fault or hypothesis.category == "config":
        return "config"
    if recent_deploy and clean_revert:
        return "rollback"
    return "patch"

