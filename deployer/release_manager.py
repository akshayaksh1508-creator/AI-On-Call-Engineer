"""Deploy / rollback executor (Day 3, A1).

- Every release is a detached git worktree under <releases_dir>/<service>/<sha12>.
- State (current + history per service) is a small JSON file.
- Each deploy/rollback appends a ChangeEvent so the agent can see it via /changes.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

from deployer.changes import ChangeLog
from deployer.runners import Runner, RunnerError

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@~^{}-]{0,127}$")


class DeployError(RuntimeError):
    pass


class ReleaseManager:
    def __init__(
        self,
        repo_dir: str | Path,
        state_path: str | Path,
        changelog: ChangeLog,
        runner: Runner,
        releases_dir: str | Path | None = None,
        allowed_services: tuple[str, ...] = ("gateway", "orders", "payments"),
        app_subdir: str = "",
    ):
        self.repo = Path(repo_dir).resolve()
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.releases = Path(releases_dir) if releases_dir else self.repo.parent / ".releases"
        self.changelog = changelog
        self.runner = runner
        self.allowed = tuple(allowed_services)
        self.app_subdir = app_subdir.strip("/")
        self._lock = threading.Lock()

    # ---------- git helpers ----------
    def _git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(self.repo), *args], capture_output=True, text=True
        )
        if proc.returncode != 0:
            raise DeployError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout.strip()

    def resolve_ref(self, ref: str) -> str:
        if not isinstance(ref, str) or not _REF_RE.match(ref) or ".." in ref:
            raise DeployError(f"invalid ref: {ref!r}")
        return self._git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")

    def commit_info(self, sha: str) -> dict[str, str]:
        out = self._git("log", "-1", "--format=%an%x1f%s", sha)
        author, _, subject = out.partition("\x1f")
        return {"commit_author": author, "subject": subject}

    # ---------- state ----------
    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8") or "{}")

    def _save(self, state: dict[str, Any]) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def _check_service(self, service: str) -> None:
        if service not in self.allowed:
            raise DeployError(f"service {service!r} not allowed (allowed: {', '.join(self.allowed)})")

    def _release_path(self, service: str, sha: str) -> Path:
        return self.releases / service / sha[:12]

    def _ensure_release(self, service: str, sha: str) -> Path:
        path = self._release_path(service, sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            self._git("worktree", "add", "--detach", str(path), sha)
        return path / self.app_subdir if self.app_subdir else path

    # ---------- public API ----------
    def bootstrap(self, service: str, ref: str) -> dict[str, Any]:
        """Record the already-running version without deploying or emitting an event."""
        with self._lock:
            self._check_service(service)
            sha = self.resolve_ref(ref)
            state = self._load()
            state[service] = {"current": sha, "history": []}
            self._save(state)
            return {"service": service, "current": sha}

    def current(self, service: str) -> str | None:
        return self._load().get(service, {}).get("current")

    def status(self) -> dict[str, Any]:
        return self._load()

    def deploy(self, service: str, ref: str, author: str = "agent", message: str = "") -> dict[str, Any]:
        with self._lock:
            self._check_service(service)
            sha = self.resolve_ref(ref)
            state = self._load()
            svc = state.setdefault(service, {"current": None, "history": []})
            cur = svc["current"]
            if cur == sha:
                return {"changed": False, "service": service, "current": sha}
            info = self.commit_info(sha)
            release_dir = self._ensure_release(service, sha)
            try:
                result = self.runner.deploy(service, release_dir, sha)
            except RunnerError as exc:
                result = type("R", (), {"ok": False, "detail": str(exc)})()
            if not result.ok:
                self._restore(service, cur)
                self.changelog.emit(
                    "deploy_failed", service, cur, sha, author, message or info["subject"],
                    meta={**info, "detail": result.detail},
                )
                raise DeployError(f"deploy of {service}@{sha[:7]} failed: {result.detail}")
            if cur:
                svc["history"].append(cur)
            svc["current"] = sha
            self._save(state)
            ev = self.changelog.emit(
                "deploy", service, cur, sha, author, message or info["subject"], meta=info
            )
            return {"changed": True, "service": service, "from": cur, "to": sha, "event": ev.to_dict()}

    def rollback(
        self, service: str, author: str = "agent", message: str = "", to_ref: str | None = None
    ) -> dict[str, Any]:
        with self._lock:
            self._check_service(service)
            state = self._load()
            svc = state.get(service)
            if not svc or not svc.get("current"):
                raise DeployError(f"{service} has no recorded current version")
            cur = svc["current"]
            if to_ref:
                target = self.resolve_ref(to_ref)
                pop = False
            elif svc["history"]:
                target = svc["history"][-1]
                pop = True
            else:
                raise DeployError(f"nothing to roll back to for {service}")
            if target == cur:
                return {"changed": False, "service": service, "current": cur}
            info = self.commit_info(target)
            release_dir = self._ensure_release(service, target)
            try:
                result = self.runner.deploy(service, release_dir, target)
            except RunnerError as exc:
                result = type("R", (), {"ok": False, "detail": str(exc)})()
            if not result.ok:
                self.changelog.emit(
                    "deploy_failed", service, cur, target, author, "rollback failed",
                    meta={**info, "detail": result.detail},
                )
                raise DeployError(f"rollback of {service} failed: {result.detail}")
            if pop:
                svc["history"].pop()
            svc["current"] = target
            self._save(state)
            ev = self.changelog.emit(
                "rollback", service, cur, target, author,
                message or f"rollback to {target[:7]}: {info['subject']}", meta=info,
            )
            return {"changed": True, "service": service, "from": cur, "to": target, "event": ev.to_dict()}

    def _restore(self, service: str, sha: str | None) -> None:
        if not sha:
            return
        try:
            self.runner.deploy(service, self._ensure_release(service, sha), sha)
        except Exception:
            pass  # best effort; the failure event is still recorded
