"""FastAPI router exposing deploy / rollback / changes. Mount in platform_api.

    from deployer.router import make_router
    app.include_router(make_router(manager, changelog))
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from deployer.changes import ChangeLog
from deployer.release_manager import DeployError, ReleaseManager


class DeployRequest(BaseModel):
    service: str
    ref: str
    author: str = "agent"
    message: str = ""


class RollbackRequest(BaseModel):
    service: str
    author: str = "agent"
    message: str = ""
    to_ref: str | None = None


def make_router(manager: ReleaseManager, changelog: ChangeLog) -> APIRouter:
    router = APIRouter(tags=["deployer"])

    @router.post("/deploy")
    def deploy(req: DeployRequest):
        try:
            return manager.deploy(req.service, req.ref, req.author, req.message)
        except DeployError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.post("/rollback")
    def rollback(req: RollbackRequest):
        try:
            return manager.rollback(req.service, req.author, req.message, req.to_ref)
        except DeployError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @router.get("/changes")
    def changes(
        since: float | None = None,
        until: float | None = None,
        service: str | None = None,
        type: str | None = None,
        limit: int | None = 100,
    ):
        return {"changes": changelog.list(since, until, service, type, limit)}

    @router.get("/versions")
    def versions():
        return manager.status()

    return router
