"""Isolated git-worktree verifier for patches, tests, and failing-request repros."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import shutil, subprocess, tempfile, time, uuid

@dataclass
class VerificationResult:
    verdict: str
    tests_passed: bool
    repro_fixed: bool
    patch_applied: bool
    worktree_cleaned: bool
    test_exit_code: int | None
    repro_exit_code: int | None
    duration_seconds: float
    details: list[str]

    def to_dict(self):
        return asdict(self)

class SandboxVerifier:
    def __init__(self, repo_path, allowed_paths=None, forbidden_paths=None, timeout=120,
                 container_image=None):
        self.repo = Path(repo_path).resolve()
        self.allowed_paths = tuple(allowed_paths or ("src/", "tests/", "config/"))
        self.forbidden_paths = tuple(forbidden_paths or (".env", "secrets/", ".git/", "infra/"))
        self.timeout = timeout
        self.container_image = container_image
        if not (self.repo / ".git").exists() and not self._is_git_worktree():
            raise ValueError(f"Not a git repository: {self.repo}")

    def _git(self, *args, cwd=None, check=True):
        return subprocess.run(["git", "-c", f"safe.directory={self.repo}", *args], cwd=cwd or self.repo, text=True,
                              capture_output=True, timeout=self.timeout, check=check)

    def _is_git_worktree(self):
        try:
            return self._git("rev-parse", "--is-inside-work-tree").returncode == 0
        except Exception:
            return False

    def _validate_patch_paths(self, patch: str):
        if not patch.strip():
            raise ValueError("Empty patch")
        touched = []
        for line in patch.splitlines():
            if line.startswith(("+++ ", "--- ")):
                name = line[4:].strip().split("\t")[0]
                if name == "/dev/null":
                    continue
                if name.startswith(("a/", "b/")):
                    name = name[2:]
                touched.append(name)
        if not touched:
            raise ValueError("Patch contains no file paths")
        for name in touched:
            normalized = Path(name)
            if normalized.is_absolute() or ".." in normalized.parts:
                raise ValueError(f"Forbidden path traversal: {name}")
            if any(name == x or name.startswith(x) for x in self.forbidden_paths):
                raise ValueError(f"Forbidden path: {name}")
            if not any(name.startswith(prefix) for prefix in self.allowed_paths):
                raise ValueError(f"Path is outside allowlist: {name}")
        return touched

    def _run_in_sandbox(self, command, worktree):
        if self.container_image:
            docker_command = [
                "docker", "run", "--rm", "--network", "none",
                "-v", f"{worktree}:/workspace", "-w", "/workspace",
                self.container_image, *command
            ]
            return subprocess.run(docker_command, text=True, capture_output=True, timeout=self.timeout)
        return subprocess.run(command, cwd=worktree, text=True, capture_output=True, timeout=self.timeout)

    def verify(self, patch: str, test_command: list[str], repro_command: list[str]) -> VerificationResult:
        started = time.monotonic()
        details = []
        worktree = self.repo.parent / f".day4-worktree-{uuid.uuid4().hex[:10]}"
        branch = f"day4-verify-{uuid.uuid4().hex[:8]}"
        test_code = repro_code = None
        applied = tests_ok = repro_ok = cleaned = False
        try:
            self._validate_patch_paths(patch)
            self._git("worktree", "add", "--detach", str(worktree), "HEAD")
            env = dict(__import__("os").environ)
            env["GIT_CONFIG_COUNT"] = "1"
            env["GIT_CONFIG_KEY_0"] = "safe.directory"
            env["GIT_CONFIG_VALUE_0"] = str(self.repo)
            apply = subprocess.run(["git", "-c", f"safe.directory={self.repo}", "apply", "--whitespace=nowarn", "-"],
                                   cwd=worktree, input=patch, text=True,
                                   capture_output=True, timeout=self.timeout, env=env)
            if apply.returncode:
                details.append("Patch application failed: " + apply.stderr.strip())
            else:
                applied = True
                details.append("Patch applied in isolated worktree.")
                tests = self._run_in_sandbox(test_command, worktree)
                test_code = tests.returncode
                tests_ok = test_code == 0
                details.append(f"Unit tests exit code: {test_code}.")
                if tests.stdout.strip(): details.append("Tests: " + tests.stdout[-1500:].strip())
                if tests.stderr.strip(): details.append("Test stderr: " + tests.stderr[-1500:].strip())
                repro = self._run_in_sandbox(repro_command, worktree)
                repro_code = repro.returncode
                repro_ok = repro_code == 0
                details.append(f"Reproduction exit code: {repro_code}.")
                if repro.stdout.strip(): details.append("Reproduction: " + repro.stdout[-1500:].strip())
                if repro.stderr.strip(): details.append("Reproduction stderr: " + repro.stderr[-1500:].strip())
        except subprocess.TimeoutExpired as exc:
            details.append(f"Sandbox command timed out after {self.timeout}s: {exc.cmd}")
        except subprocess.CalledProcessError as exc:
            details.append(f"Git command failed: {exc.cmd}; {exc.stderr or exc.stdout or exc}")
        except Exception as exc:
            details.append(f"Verification rejected/failed: {type(exc).__name__}: {exc}")
        finally:
            try:
                if worktree.exists():
                    self._git("worktree", "remove", "--force", str(worktree), check=False)
                self._git("worktree", "prune", check=False)
                cleaned = not worktree.exists()
            except Exception as exc:
                details.append(f"Cleanup warning: {exc}")
        verdict = "pass" if applied and tests_ok and repro_ok and cleaned else "fail"
        return VerificationResult(verdict, tests_ok, repro_ok, applied, cleaned,
                                  test_code, repro_code, round(time.monotonic()-started, 3), details)
