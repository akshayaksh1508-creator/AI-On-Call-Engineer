"""FastAPI router for the repo tools. Mount in platform_api:

    from platform_api.repo_router import make_repo_router
    app.include_router(make_repo_router(RepoTools(REPO_DIR, root_subdir="target-app")))
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from platform_api.repo_tools import RepoToolError, RepoTools


def make_repo_router(tools: RepoTools) -> APIRouter:
    router = APIRouter(prefix="/repo", tags=["repo"])

    def guard(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RepoToolError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc))

    @router.get("/log")
    def log(path: str | None = None, since: str | None = None, until: str | None = None, n: int = 20, ref: str = "HEAD"):
        return {"commits": guard(tools.git_log, path, since, until, n, ref)}

    @router.get("/diff")
    def diff(commit: str | None = None, base: str | None = None, head: str | None = None, path: str | None = None):
        return guard(tools.git_diff, commit, base, head, path)

    @router.get("/file")
    def file(path: str, ref: str | None = None, start_line: int | None = None, end_line: int | None = None):
        return guard(tools.read_file, path, ref, start_line, end_line)

    return router
