"""Validate generated regression tests and prove fail-before/pass-after."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class RegressionTestError(ValueError):
    """Raised when generated regression test code is invalid or unsafe."""


@dataclass(frozen=True)
class RegressionResult:
    failed_before: bool
    passed_after: bool
    before_exit_code: int
    after_exit_code: int
    before_output: str
    after_output: str

    @property
    def verified(self) -> bool:
        return self.failed_before and self.passed_after


def write_regression_test(fault_id: str, source: str, output_dir: str | Path) -> Path:
    """Store generated pytest code only when it contains an executable assertion."""
    if not re.fullmatch(r"fault_[a-zA-Z0-9_-]+", fault_id):
        raise RegressionTestError("Invalid fault ID for generated test filename")
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise RegressionTestError(f"Generated test has invalid Python syntax: {exc}") from exc
    test_functions = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    test_classes = [
        node for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(
            (isinstance(base, ast.Name) and base.id == "TestCase")
            or (isinstance(base, ast.Attribute) and base.attr == "TestCase")
            for base in node.bases
        )
    ]
    test_methods = [
        node for cls in test_classes for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    ]
    test_nodes = test_functions + test_methods
    if not test_nodes:
        raise RegressionTestError("Generated test must define a test_* function or unittest.TestCase method")
    has_assertion = any(
        isinstance(node, ast.Assert)
        or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.startswith("assert")
        )
        for fn in test_nodes for node in ast.walk(fn)
    )
    if not has_assertion:
        raise RegressionTestError("Generated regression test must contain an assertion")
    destination = Path(output_dir).resolve() / "tests" / "generated"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"test_{fault_id}.py"
    path.write_text(source.rstrip() + "\n", encoding="utf-8")
    return path


def verify_fail_then_pass(
    test_path: str | Path,
    before_root: str | Path,
    after_root: str | Path,
    command: Sequence[str] | None = None,
    timeout: int = 120,
) -> RegressionResult:
    """Run the same regression against separate buggy and fixed checkouts."""
    test_path = Path(test_path).resolve()
    before_root, after_root = Path(before_root).resolve(), Path(after_root).resolve()
    if not test_path.is_file():
        raise RegressionTestError(f"Regression test does not exist: {test_path}")

    def run(root: Path) -> subprocess.CompletedProcess[str]:
        root_test = root / "tests" / "generated" / test_path.name
        root_test.parent.mkdir(parents=True, exist_ok=True)
        root_test.write_bytes(test_path.read_bytes())
        try:
            argv = [*(command or (sys.executable,)), str(root_test)]
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout, tempfile.TemporaryFile(
                mode="w+t", encoding="utf-8"
            ) as stderr:
                result = subprocess.run(
                    argv, cwd=root, env={**os.environ, "PYTHONPATH": str(root)},
                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                    timeout=timeout, check=False,
                )
                stdout.seek(0)
                stderr.seek(0)
                return subprocess.CompletedProcess(argv, result.returncode, stdout.read(), stderr.read())
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(command or (), 124, "", "test command timed out")

    before = run(before_root)
    after = run(after_root)
    return RegressionResult(
        failed_before=before.returncode != 0,
        passed_after=after.returncode == 0,
        before_exit_code=before.returncode,
        after_exit_code=after.returncode,
        before_output=(before.stdout or "") + (before.stderr or ""),
        after_output=(after.stdout or "") + (after.stderr or ""),
    )
