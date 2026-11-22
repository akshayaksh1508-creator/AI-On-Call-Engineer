"""FastAPI Stub Platform API.

Implements the 9 platform tool endpoints specified in Day 1 / Task A4.
Can be run as a standalone HTTP service or in-process via Starlette/httpx TestClient.
"""

from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Query, HTTPException, Body
from pydantic import BaseModel

from contracts.models import FixProposal, FixProposalReceipt
from platform_api.fixture_client import FixtureClient


class LogQueryRequest(BaseModel):
    service: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    level: Optional[str] = None
    trace_id: Optional[str] = None
    limit: int = 100


class MetricQueryRequest(BaseModel):
    metric_name: str
    start: Optional[str] = None
    end: Optional[str] = None
    step: str = "15s"


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 3


def create_platform_api_app(fixture_bundle: str = "fault_001_bad_deploy") -> FastAPI:
    """Factory creating the FastAPI Stub Platform API app."""
    app = FastAPI(
        title="NightShift Stub Platform API",
        description="Emulates production observability, git, service map, and remediation endpoints.",
        version="1.0.0",
    )

    client = FixtureClient(fixture_bundle=fixture_bundle)

    @app.get("/health")
    def health():
        return {"status": "ok", "app": "nightshift-stub-platform-api", "fixture": fixture_bundle}

    # Tool 1: Query Logs (supports both GET and POST)
    @app.get("/logs/query")
    def get_logs(
        service: Optional[str] = Query(None),
        start: Optional[str] = Query(None),
        end: Optional[str] = Query(None),
        level: Optional[str] = Query(None),
        trace_id: Optional[str] = Query(None),
        limit: int = Query(100),
    ):
        return client.query_logs(
            service=service, start=start, end=end, level=level, trace_id=trace_id, limit=limit
        )

    @app.post("/logs/query")
    def post_logs(req: LogQueryRequest):
        return client.query_logs(
            service=req.service,
            start=req.start,
            end=req.end,
            level=req.level,
            trace_id=req.trace_id,
            limit=req.limit,
        )

    # Tool 2: Query Metrics (supports both GET and POST)
    @app.get("/metrics/query")
    def get_metrics(
        metric_name: str = Query("http_requests_total"),
        start: Optional[str] = Query(None),
        end: Optional[str] = Query(None),
        step: str = Query("15s"),
    ):
        return client.query_metrics(metric_name=metric_name, start=start, end=end, step=step)

    @app.post("/metrics/query")
    def post_metrics(req: MetricQueryRequest):
        return client.query_metrics(
            metric_name=req.metric_name, start=req.start, end=req.end, step=req.step
        )

    # Tool 3: List Changes
    @app.get("/changes")
    def list_changes(
        service: Optional[str] = Query(None),
        since: Optional[str] = Query(None),
        limit: int = Query(10),
    ):
        return client.list_changes(service=service, since=since, limit=limit)

    # Tool 4: Git Log
    @app.get("/repo/log")
    def git_log(
        n: int = Query(10),
        path: Optional[str] = Query(None),
    ):
        return client.git_log(n=n, path=path)

    # Tool 5: Git Diff
    @app.get("/repo/diff")
    def git_diff(
        commit_a: str = Query(..., description="Commit SHA or ref"),
        commit_b: Optional[str] = Query(None),
        path: Optional[str] = Query(None),
    ):
        diff = client.git_diff(commit_a=commit_a, commit_b=commit_b, path=path)
        return {"diff": diff}

    # Tool 6: Read File
    @app.get("/repo/show")
    def read_file(
        path: str = Query(...),
        ref: Optional[str] = Query(None),
        start_line: Optional[int] = Query(None),
        end_line: Optional[int] = Query(None),
    ):
        content = client.read_file(path=path, ref=ref, start_line=start_line, end_line=end_line)
        return {"path": path, "content": content}

    # Tool 7: Service Map
    @app.get("/service-map")
    def service_map():
        return client.service_map()

    # Tool 8: Search Past Incidents
    @app.get("/memory/search")
    def get_past_incidents(
        query: str = Query(...),
        limit: int = Query(3),
    ):
        return client.search_past_incidents(query=query, limit=limit)

    @app.post("/memory/search")
    def post_past_incidents(req: MemorySearchRequest):
        return client.search_past_incidents(query=req.query, limit=req.limit)

    # Tool 9: Propose Fix
    @app.post("/fix/propose")
    def propose_fix(proposal: FixProposal):
        receipt = client.propose_fix(proposal)
        return receipt

    return app


# Default ASGI app instance
app = create_platform_api_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("platform_api.stub_app:app", host="127.0.0.1", port=8000, reload=True)
