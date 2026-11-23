"""Safe, read-only git/file tools for the agent (Day 3, A2).

Tools exposed: git_log, git_diff, read_file.
Safety: path allowlist (everything must stay inside `root_subdir`), no `..`,
no absolute paths, no symlink escapes, secret-file deny list, output size caps.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@~^{}-]{0,127}$")

DENY_GLOBS = (".env", ".env.*", "*.pem", "*.key", "*.p12", "id_rsa*", "*secret*", "*credentials*", ".git", ".git/*")
EXCLUDE_PATHSPECS = (
    ":(exclude,glob)**/.env*",
    ":(exclude,glob)**/*.pem",
    ":(exclude,glob)**/*.key",
    ":(exclude,glob)**/*secret*",
    ":(exclude,glob)**/*credentials*",
)


class RepoToolError(Exception):
    """Raised for rejected or failed requests; routers map this to HTTP 400/403."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def to_epoch(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    try:
        return float(s)
    except ValueError:
        pass
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


class RepoTools:
    def __init__(
        self,
        repo_dir: str | Path,
        root_subdir: str = "",
        max_bytes: int = 20_000,
        max_diff_bytes: int = 30_000,
        max_log: int = 50,
    ):
        self.repo = Path(repo_dir).resolve()
        self.root = root_subdir.strip("/")
        self.max_bytes = max_bytes
        self.max_diff_bytes = max_diff_bytes
        self.max_log = max_log

    # ---------- validation ----------
    def _check_ref(self, ref: str) -> str:
        if not isinstance(ref, str) or not _REF_RE.match(ref) or ".." in ref:
            raise RepoToolError(f"invalid ref: {ref!r}")
        return ref

    def _safe_rel(self, path: str) -> str:
        """Return a clean posix path relative to the allowed root."""
        if path is None or path == "":
            return ""
        if "\x00" in path or "\\" in path:
            raise RepoToolError("invalid characters in path", 403)
        p = PurePosixPath(path)
        if p.is_absolute() or ".." in p.parts:
            raise RepoToolError("path escapes the allowed directory", 403)
        rel = str(p) if str(p) != "." else ""
        for part_idx in range(len(p.parts)):
            sub = "/".join(p.parts[: part_idx + 1])
            for pattern in DENY_GLOBS:
                if fnmatch.fnmatch(p.parts[part_idx].lower(), pattern) or fnmatch.fnmatch(sub.lower(), pattern):
                    raise RepoToolError(f"access to {path!r} is denied", 403)
        return rel

    def _repo_path(self, rel: str) -> str:
        if self.root and rel:
            return f"{self.root}/{rel}"
        return self.root or rel

    def _git(self, *args: str) -> str:
        proc = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RepoToolError(f"git error: {proc.stderr.strip()[:300]}")
        return proc.stdout

    def _pathspec(self, rel: str) -> list[str]:
        return ["--", self._repo_path(rel) or ".", *EXCLUDE_PATHSPECS]

    # ---------- tools ----------
    def git_log(
        self,
        path: str | None = None,
        since: Any = None,
        until: Any = None,
        n: int = 20,
        ref: str = "HEAD",
    ) -> list[dict[str, Any]]:
        rel = self._safe_rel(path or "")
        self._check_ref(ref)
        n = max(1, min(int(n), self.max_log))
        fmt = "%H%x1f%an%x1f%ct%x1f%s"
        out = self._git("log", f"-n{500}", f"--format={fmt}", ref, *self._pathspec(rel))
        lo, hi = to_epoch(since), to_epoch(until)
        commits: list[dict[str, Any]] = []
        for line in out.splitlines():
            sha, author, ct, subject = line.split("\x1f", 3)
            ts = float(ct)
            if (lo is not None and ts < lo) or (hi is not None and ts > hi):
                continue
            commits.append(
                {
                    "sha": sha,
                    "short": sha[:7],
                    "author": author,
                    "ts": ts,
                    "ts_iso": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "subject": subject,
                }
            )
            if len(commits) >= n:
                break
        return commits

    def git_diff(
        self,
        commit: str | None = None,
        base: str | None = None,
        head: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        rel = self._safe_rel(path or "")
        spec = self._pathspec(rel)
        if commit:
            self._check_ref(commit)
            revs = [commit]
            patch = self._git("show", "--format=", "--patch", "--no-color", commit, *spec)
            stat = self._git("show", "--format=", "--numstat", commit, *spec)
        elif base and head:
            self._check_ref(base)
            self._check_ref(head)
            patch = self._git("diff", "--no-color", base, head, *spec)
            stat = self._git("diff", "--numstat", base, head, *spec)
            revs = [base, head]
        else:
            raise RepoToolError("provide `commit` or both `base` and `head`")
        files = []
        for line in stat.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                files.append({"path": parts[2], "added": parts[0], "deleted": parts[1]})
        truncated = len(patch) > self.max_diff_bytes
        return {
            "revs": revs,
            "files": files,
            "diff": patch[: self.max_diff_bytes],
            "truncated": truncated,
        }

    def read_file(
        self,
        path: str,
        ref: str | None = None,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        rel = self._safe_rel(path)
        if not rel:
            raise RepoToolError("path is required")
        repo_rel = self._repo_path(rel)
        if ref:
            self._check_ref(ref)
            text = self._git("show", f"{ref}:{repo_rel}")
        else:
            full = (self.repo / repo_rel)
            try:
                resolved = full.resolve(strict=True)
            except FileNotFoundError:
                raise RepoToolError(f"file not found: {path}", 404)
            allowed_root = (self.repo / self.root).resolve() if self.root else self.repo
            if allowed_root != resolved and allowed_root not in resolved.parents:
                raise RepoToolError("path escapes the allowed directory", 403)
            if not resolved.is_file():
                raise RepoToolError(f"not a file: {path}", 404)
            text = resolved.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        if start_line or end_line:
            s = max(1, int(start_line or 1))
            e = min(total, int(end_line or total))
            lines = lines[s - 1 : e]
            text = "\n".join(lines)
        truncated = len(text) > self.max_bytes
        return {
            "path": rel,
            "ref": ref or "working-tree",
            "total_lines": total,
            "content": text[: self.max_bytes],
            "truncated": truncated,
        }
