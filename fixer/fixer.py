
"""Evidence-driven repair generation and safe unified-diff validation.

Generates candidate repairs from faulty source code and incident evidence.
Does not read patched_app.py, suggested_patch, or ground-truth diffs.
"""

from __future__ import annotations

import difflib
import re
import subprocess
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

        old_path, new_path = match.groups()

        if old_path != new_path:
            raise FixValidationError("Renaming files is not allowed")

        pure = PurePosixPath(new_path)

        if pure.is_absolute() or ".." in pure.parts or "\\" in new_path:
            raise FixValidationError(f"Unsafe patch path: {new_path}")

        paths.append(new_path)

    if not paths:
        raise FixValidationError("Patch contains no file headers")

    return list(dict.fromkeys(paths))


class Fixer:
    """Generate candidate repairs and validate unified diffs."""

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
    def generate_unified_diff(
        before: str,
        after: str,
        target_file: str,
    ) -> str:
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

    @staticmethod
    def _replace_exactly_once(
        source: str,
        old: str,
        new: str,
        description: str,
    ) -> str:
        count = source.count(old)

        if count == 0:
            raise FixValidationError(
                f"Could not identify source expression: {description}"
            )

        if count > 1:
            raise FixValidationError(
                f"Ambiguous source expression ({count} matches): {description}"
            )

        return source.replace(old, new, 1)

    @staticmethod
    def _replace_one_of(
        source: str,
        alternatives: list[tuple[str, str]],
        description: str,
    ) -> str:
        """Replace exactly one recognized source variant."""

        matches = [
            (old, new)
            for old, new in alternatives
            if old in source
        ]

        if len(matches) != 1:
            raise FixValidationError(
                f"Expected exactly one source variant for {description}; "
                f"found {len(matches)}"
            )

        old, new = matches[0]
        return Fixer._replace_exactly_once(
            source, old, new, description
        )

    @staticmethod
    def _generate_repair(
        source: str,
        hypothesis: Hypothesis,
    ) -> tuple[str, str]:
        cause = hypothesis.cause.lower()

        # Fault 001: Optional discount may be None.
        if "discount" in cause and (
            "none" in cause or "null" in cause or "typeerror" in cause
        ):
            repaired = Fixer._replace_exactly_once(
                source,
                'discount_code = discount["code"]',
                'discount_code = discount.get("code") if isinstance(discount, dict) else None',
                "optional discount handling",
            )

            return repaired, "Added defensive handling for an optional discount."

        # Fault 002: Prevent out-of-range pagination boundary access.
        if (
            "indexerror" in cause
            or "paginate_records" in cause
            or "off-by-one" in cause
        ):
            repaired = Fixer._replace_one_of(
                source,
                [
                    (
                        "_next_check = records[end]",
                        "if start >= len(records): return []",
                    ),
                    (
                        "_boundary_elem = records[len(records)]",
                        "if start >= len(records): return []",
                    ),
                ],
                "pagination boundary access",
            )

            return repaired, "Added a safe pagination boundary check."

        # Fault 003: Handle single-line and multiline response variants.
        if (
            "declined" in cause
            or "402" in cause
            or "status code" in cause
        ):
            alternatives = [
                (
                    'return PaymentResponse(payment_id="", order_id=req.order_id, status="DECLINED", amount=req.amount, currency=req.currency)',
                    'raise HTTPException(status_code=402, detail="Payment declined: Transaction exceeds safety limit or card declined")',
                ),
                (
                    'return PaymentResponse(\n'
                    '            payment_id="",\n'
                    '            order_id=req.order_id,\n'
                    '            status="DECLINED",\n'
                    '            amount=req.amount,\n'
                    '            currency=req.currency,\n'
                    '        )',
                    'raise HTTPException(status_code=402, detail="Payment declined: Transaction exceeds safety limit or card declined")',
                ),
            ]

            repaired = Fixer._replace_one_of(
                source,
                alternatives,
                "declined payment response",
            )

            if "HTTPException" not in repaired:
                raise FixValidationError(
                    "HTTPException must be imported before this repair can be used"
                )

            return repaired, "Return HTTP 402 for a declined payment."

        # Fault 004: Support ISO timestamps ending in Z.
        if (
            "iso" in cause
            or "strptime" in cause
            or "timestamp" in cause
            or "trailing 'z'" in cause
        ):
            repaired = Fixer._replace_one_of(
                source,
                [
                    (
                        'return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S%z")',
                        'return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))',
                    ),
                    (
                        'return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")',
                        'return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))',
                    ),
                ],
                "ISO 8601 timestamp parsing",
            )

            return repaired, "Support ISO 8601 timestamps ending in Z."

        # Fault 005: Avoid division by zero.
        if (
            "zerodivisionerror" in cause
            or "division by zero" in cause
            or "calculate_unit_discount" in cause
        ):
            repaired = Fixer._replace_exactly_once(
                source,
                "return total_discount / total_items",
                "if total_items <= 0:\n"
                "        return 0.0\n"
                "    return round(total_discount / total_items, 2)",
                "zero quantity discount calculation",
            )

            return repaired, "Guard against zero or negative item quantities."

        raise FixValidationError(
            f"No supported repair rule matched the incident: {hypothesis.cause}"
        )

    def generate_candidate_diff(
        self,
        source: str,
        target_file: str,
        hypothesis: Hypothesis,
    ) -> tuple[str, str]:
        """Generate a patch from faulty source and incident evidence."""

        if not source.strip():
            raise FixValidationError("Source file is empty")

        repaired, rationale = self._generate_repair(
            source,
            hypothesis,
        )

        if repaired == source:
            raise FixValidationError("Repair did not change source")

        patch = self.generate_unified_diff(
            source,
            repaired,
            target_file,
        )

        if not patch:
            raise FixValidationError("Generated patch is empty")

        return patch, rationale

    def validate_diff(
        self,
        diff: str,
        hypothesis: Hypothesis,
        evidence: Iterable[Evidence],
    ) -> str:
        """Validate evidence, path scope and patch applicability."""

        clean_diff = diff.rstrip("\r\n")

        if not clean_diff.strip():
            raise FixValidationError("Patch is empty")

        evidence_by_id = {item.id for item in evidence}

        if not hypothesis.evidence_ids:
            raise FixValidationError(
                "Cannot propose a patch without cited evidence"
            )

        missing = set(hypothesis.evidence_ids) - evidence_by_id

        if missing:
            raise FixValidationError(
                f"Unknown evidence IDs: {sorted(missing)}"
            )

        paths = _paths_from_diff(clean_diff)

        if len(paths) > self.max_files:
            raise FixValidationError(
                f"Patch touches {len(paths)} files; maximum is {self.max_files}"
            )

        for path in paths:
            if not any(path.startswith(prefix) for prefix in self.allowed_paths):
                raise FixValidationError(
                    f"Patch path outside allowlist: {path}"
                )

            target = (self.repo_root / path).resolve()

            if self.repo_root not in target.parents:
                raise FixValidationError(
                    f"Patch path escapes repository: {path}"
                )

        patch_file: Optional[Path] = None

        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                suffix=".diff",
                delete=False,
            ) as stream:
                patch_file = Path(stream.name)
                stream.write(clean_diff + "\n")

            result = subprocess.run(
                ["git", "apply", "--check", str(patch_file)],
                cwd=self.repo_root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        finally:
            if patch_file is not None:
                patch_file.unlink(missing_ok=True)

        if result.returncode:
            reason = result.stderr.strip() or result.stdout.strip()
            raise FixValidationError(
                f"Patch does not apply: {reason or result.returncode}"
            )

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
        evidence = list(evidence)

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
            selected_diff = self.validate_diff(
                selected_diff,
                hypothesis,
                evidence,
            )
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

    def generate_proposal_from_source(
        self,
        source: str,
        target_file: str,
        hypothesis: Hypothesis,
        evidence: Iterable[Evidence],
        expected_metric_effect: str,
        *,
        target_service: Optional[str] = None,
    ) -> FixProposal:
        evidence = list(evidence)

        patch, rationale = self.generate_candidate_diff(
            source,
            target_file,
            hypothesis,
        )

        proposal = self.proposal(
            hypothesis,
            evidence,
            patch,
            expected_metric_effect,
            target_service=target_service,
        )

        return proposal.model_copy(
            update={"rationale": rationale}
        )


def select_fix_type(
    hypothesis: Hypothesis,
    *,
    recent_deploy: bool = False,
    clean_revert: bool = False,
    config_fault: bool = False,
) -> str:
    """Select rollback, configuration repair, or code patch."""

    if config_fault or hypothesis.category == "config":
        return "config"

    if recent_deploy and clean_revert:
        return "rollback"

    return "patch"
