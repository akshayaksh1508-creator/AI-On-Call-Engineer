"""Isolated patch verification in an ephemeral Git worktree."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence

from contracts.models import VerificationResult


@dataclass(frozen=True)
class SandboxRun:
    verification: VerificationResult
    accepted: bool
    error: Optional[str]
    reproduction_failed_before: bool
    unit_test_output: str
    reproduction_output: str


class SandboxVerifier:
    """Apply a proposed patch to a one-run worktree and verify test plus repro."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        use_container: bool = True,
        docker_image: str = "nightshift-verifier:day4",
        timeout: int = 120,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.use_container = use_container
        self.docker_image = docker_image
        self.timeout = min(max(timeout, 1), 120)

    def verify(
        self,
        incident_id: str,
        patch: str,
        *,
        target_file: str,
        faulty_file: Optional[str] = None,
        reproduction_command: Optional[Sequence[str]] = None,
        test_command: Sequence[str] = ("python", "-m", "pytest", "-q"),
        base_ref: str = "HEAD",
    ) -> SandboxRun:
        """Return a partial VerificationResult; canary and recovery are Day 5."""
        try:
            safe_target = self._allowed_target(target_file)
        except ValueError as exc:
            return self._rejected(str(exc))
        if not patch.strip():
            return self._rejected("Patch is empty")
        if not reproduction_command:
            return self._rejected("A fault-specific reproduction command is required")
        patch_paths = self._patch_paths(patch)
        if not patch_paths:
            return self._rejected("Patch contains no Git file headers")
        if any(path != safe_target for path in patch_paths):
            return self._rejected(
                f"Patch may only modify {safe_target}; found {', '.join(patch_paths)}"
            )

        incident_key = hashlib.sha256(incident_id.encode("utf-8")).hexdigest()[:16]
        sandbox_parent = self.repo_root.parent / ".nightshift-sandboxes"
        sandbox_parent.mkdir(parents=True, exist_ok=True)
        worktree = Path(tempfile.mkdtemp(prefix=f"{incident_key}-", dir=sandbox_parent))
        shutil.rmtree(worktree)
        patch_file = sandbox_parent / f"{incident_key}-{uuid.uuid4().hex[:8]}.diff"
        patch_file.write_text(patch.rstrip("\r\n") + "\n", encoding="utf-8")
        registered = False
        try:
            self._git("worktree", "add", "--detach", str(worktree), base_ref)
            registered = True
            self._overlay_working_changes(worktree)
            if faulty_file:
                source = self._repo_file(faulty_file)
                target = worktree / safe_target
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

            baseline_reproduction = self._run(reproduction_command, worktree, self.timeout)
            if baseline_reproduction.returncode == 0:
                return self._failed(
                    "Reproduction did not fail on the faulty baseline",
                    repro_output=self._output(baseline_reproduction),
                )

            check = self._run(["git", "apply", "--check", str(patch_file)], worktree, 10)
            if check.returncode:
                detail = check.stderr.strip() or check.stdout.strip() or "git apply --check failed"
                return self._failed(f"Patch does not apply: {detail}")
            applied = self._run(["git", "apply", str(patch_file)], worktree, 10)
            if applied.returncode:
                return self._failed(f"Patch application failed: {applied.stderr.strip()}")

            if self.use_container:
                tests = self._run_in_container(worktree, test_command)
            else:
                tests = self._run(test_command, worktree, self.timeout)
            reproduction = self._run(reproduction_command, worktree, self.timeout)
            tests_passed = tests.returncode == 0
            repro_passed = reproduction.returncode == 0
            if not tests_passed or not repro_passed:
                return self._failed(
                    "Unit tests failed" if not tests_passed else "Failing-request reproduction did not pass",
                    unit_output=self._output(tests),
                    repro_output=self._output(reproduction),
                    reproduction_failed_before=True,
                )
            return SandboxRun(
                verification=VerificationResult(
                    tests_passed=True,
                    repro_fixed=True,
                    canary_healthy=False,
                    metric_before=0.0,
                    metric_after=0.0,
                    verdict="PASS",
                ),
                accepted=True,
                error=None,
                reproduction_failed_before=True,
                unit_test_output=self._output(tests),
                reproduction_output=self._output(reproduction),
            )
        except subprocess.TimeoutExpired as exc:
            return self._failed(
                f"Sandbox command exceeded {self.timeout}s timeout",
                unit_output=self._exception_output(exc),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return self._failed(f"Sandbox execution error: {exc}")
        finally:
            if registered:
                self._git("worktree", "remove", "--force", str(worktree), check=False)
            shutil.rmtree(worktree, ignore_errors=True)
            patch_file.unlink(missing_ok=True)

    def _run_in_container(self, worktree: Path, test_command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        docker = shutil.which("docker")
        if not docker:
            raise OSError("Docker is required for sandbox unit tests but is not installed")
        image = self._run([docker, "image", "inspect", self.docker_image], self.repo_root, 15)
        if image.returncode:
            dockerfile = self.repo_root / "verifier" / "Dockerfile"
            build = self._run(
                [docker, "build", "-t", self.docker_image, "-f", str(dockerfile), str(self.repo_root)],
                self.repo_root, 300,
            )
            if build.returncode:
                raise OSError(f"Could not build verifier test image: {build.stderr[-1000:]}")
        return self._run(
            [
                docker, "run", "--rm", "--network", "none",
                "--volume", f"{worktree.as_posix()}:/workspace",
                "--workdir", "/workspace", self.docker_image, *test_command,
            ],
            worktree, self.timeout,
        )

    def _overlay_working_changes(self, worktree: Path) -> None:
        """Mirror local edits into the worktree so uncommitted Day 4 code is tested."""
        changed = self._git("diff", "--name-only", "HEAD", check=False).stdout.splitlines()
        untracked = self._git("ls-files", "--others", "--exclude-standard", check=False).stdout.splitlines()
        for relative in dict.fromkeys(changed + untracked):
            try:
                source = self._repo_file(relative)
            except ValueError:
                continue
            target = worktree / relative
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            elif source.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

    def _allowed_target(self, path: str) -> str:
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or "\\" in path:
            raise ValueError(f"Forbidden target path: {path}")
        if not path.startswith("target-app/"):
            raise ValueError(f"Forbidden target path: {path}")
        self._repo_file(path)
        return path

    @staticmethod
    def _patch_paths(patch: str) -> list[str]:
        paths: list[str] = []
        for line in patch.splitlines():
            if line.startswith("diff --git a/"):
                sides = line[len("diff --git a/"):].split(" b/", 1)
                if len(sides) != 2:
                    return []
                old_path, new_path = sides
                if old_path != new_path:
                    return []
                paths.append(new_path)
        return list(dict.fromkeys(paths))

    def _repo_file(self, relative: str) -> Path:
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
            raise ValueError(f"Unsafe repository path: {relative}")
        result = (self.repo_root / Path(*pure.parts)).resolve()
        if result != self.repo_root and self.repo_root not in result.parents:
            raise ValueError(f"Repository path escapes checkout: {relative}")
        return result

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = self._run(["git", *args], self.repo_root, 30)
        if check and result.returncode:
            raise OSError(result.stderr.strip() or result.stdout.strip() or f"git {' '.join(args)} failed")
        return result

    @staticmethod
    def _run(command: Sequence[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout, tempfile.TemporaryFile(
            mode="w+t", encoding="utf-8"
        ) as stderr:
            result = subprocess.run(
                list(command), cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                timeout=timeout, check=False,
            )
            stdout.seek(0)
            stderr.seek(0)
            return subprocess.CompletedProcess(
                list(command), result.returncode, stdout.read(), stderr.read()
            )

    @staticmethod
    def _output(result: subprocess.CompletedProcess[str]) -> str:
        return (result.stdout + result.stderr)[-8000:]

    @staticmethod
    def _exception_output(exc: subprocess.TimeoutExpired) -> str:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return (stdout + stderr)[-8000:]

    @staticmethod
    def _failed(
        error: str, unit_output: str = "", repro_output: str = "",
        reproduction_failed_before: bool = False,
    ) -> SandboxRun:
        return SandboxRun(
            verification=VerificationResult(
                tests_passed=False,
                repro_fixed=False,
                canary_healthy=False,
                metric_before=0.0,
                metric_after=0.0,
                verdict="FAIL",
            ),
            accepted=True,
            error=error,
            reproduction_failed_before=reproduction_failed_before,
            unit_test_output=unit_output,
            reproduction_output=repro_output,
        )

    @staticmethod
    def _rejected(error: str) -> SandboxRun:
        result = SandboxVerifier._failed(error)
        return SandboxRun(
            verification=result.verification.model_copy(update={"verdict": "ESCALATE"}),
            accepted=False,
            error=error,
            reproduction_failed_before=False,
            unit_test_output="",
            reproduction_output="",
        )
