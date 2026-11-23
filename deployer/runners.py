"""Runners actually start a release. Swap NoopRunner (tests) / ComposeRunner (real).

Owner: Person A.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence


class RunnerError(RuntimeError):
    pass


@dataclass
class RunResult:
    ok: bool
    detail: str = ""


class Runner(Protocol):
    def deploy(self, service: str, release_dir: Path, sha: str) -> RunResult: ...

    def recreate(self, services: Sequence[str], compose_files: Sequence[str] | None = None) -> RunResult: ...


@dataclass
class NoopRunner:
    """Records calls; used by unit tests and dry runs."""

    fail_shas: set[str] = field(default_factory=set)
    calls: list[tuple] = field(default_factory=list)

    def deploy(self, service: str, release_dir: Path, sha: str) -> RunResult:
        self.calls.append(("deploy", service, str(release_dir), sha))
        if sha in self.fail_shas:
            return RunResult(False, "simulated failure")
        return RunResult(True, "noop")

    def recreate(self, services, compose_files=None) -> RunResult:
        self.calls.append(("recreate", tuple(services), tuple(compose_files or ())))
        return RunResult(True, "noop")


def _default_exec(cmd: list[str], env: dict[str, str]) -> str:
    proc = subprocess.run(
        cmd, env={**os.environ, **env}, capture_output=True, text=True, timeout=600
    )
    if proc.returncode != 0:
        raise RunnerError(f"{' '.join(cmd)} failed: {proc.stderr.strip()[-500:]}")
    return proc.stdout


def _default_health(url: str) -> tuple[bool, str | None]:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            if resp.status != 200:
                return False, None
            body = resp.read().decode("utf-8", "replace")
        try:
            return True, json.loads(body).get("version")
        except Exception:
            return True, None
    except Exception:
        return False, None


class ComposeRunner:
    """Rebuilds one service from a release directory with docker compose.

    Your compose file must read `<SERVICE>_RELEASE_DIR` and `<SERVICE>_VERSION`
    (see docs/DAY3_README.md for the snippet).
    """

    def __init__(
        self,
        compose_file: str,
        health_urls: dict[str, str] | None = None,
        health_timeout: float = 60.0,
        exec_fn: Callable[[list[str], dict[str, str]], str] | None = None,
        health_fn: Callable[[str], tuple[bool, str | None]] | None = None,
    ):
        self.compose_file = compose_file
        self.health_urls = health_urls or {}
        self.health_timeout = health_timeout
        self.exec_fn = exec_fn or _default_exec
        self.health_fn = health_fn or _default_health

    def deploy(self, service: str, release_dir: Path, sha: str) -> RunResult:
        key = service.upper().replace("-", "_")
        env = {f"{key}_RELEASE_DIR": Path(release_dir).as_posix(), f"{key}_VERSION": sha}
        self.exec_fn(
            ["docker", "compose", "-f", self.compose_file, "up", "-d", "--build", "--no-deps", service],
            env,
        )
        url = self.health_urls.get(service)
        if not url:
            return RunResult(True, "started (no health url configured)")
        deadline = time.time() + self.health_timeout
        while time.time() < deadline:
            ok, version = self.health_fn(url)
            if ok and (version is None or sha.startswith(version) or version.startswith(sha[:7])):
                return RunResult(True, f"healthy version={version}")
            time.sleep(1.0)
        return RunResult(False, f"{service} not healthy with version {sha[:7]} after {self.health_timeout}s")

    def recreate(self, services: Sequence[str], compose_files: Sequence[str] | None = None) -> RunResult:
        files = list(compose_files or [self.compose_file])
        cmd = ["docker", "compose"]
        for f in files:
            cmd += ["-f", f]
        cmd += ["up", "-d", "--no-deps", "--force-recreate", *services]
        self.exec_fn(cmd, {})
        return RunResult(True, "recreated")
