"""FastAPI Platform API Server for NightShift Observability and Remediation.

Owner: Person A (Systems & Proof)
Serves the 9 standard diagnostic and remediation endpoints specified in Section 4.
Modes:
- 'real' (default): Operates against live production logs, Prometheus, and data/changes.json.
- 'fixture': Operates against offline recorded incident bundles for test reproducibility.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Query, HTTPException, Body
from pydantic import BaseModel, Field

from contracts.models import FixProposal, FixProposalReceipt
from platform_api.client import PlatformClient
from platform_api.fixture_client import FixtureClient
from platform_api.real_client import RealPlatformClient
from verifier.engine import FullVerifier
from verifier.sandbox import SandboxVerifier


class LogQueryRequest(BaseModel):
    service: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    level: Optional[str] = None
    trace_id: Optional[str] = None
    limit: int = 100
    text: Optional[str] = None


class MetricQueryRequest(BaseModel):
    metric_name: str
    start: Optional[str] = None
    end: Optional[str] = None
    step: str = "15s"


class MemorySearchRequest(BaseModel):
    query: str
    limit: int = 3


def create_platform_api_app(
    mode: str = "real",
    fixture_bundle: str = "fault_001_bad_deploy",
    repo_root: Optional[Path] = None,
    sandbox_use_container: bool = True,
) -> FastAPI:
    """Factory creating the FastAPI Platform API app."""
    app = FastAPI(
        title="NightShift Platform API",
        description="Unified observability, telemetry, git, and remediation endpoints for autonomous SRE agents.",
        version="2.0.0",
    )

    if mode == "real":
        client: PlatformClient = RealPlatformClient(repo_root=repo_root)
    else:
        client = FixtureClient(fixture_bundle=fixture_bundle)

    repository_root = Path(repo_root or Path(__file__).resolve().parent.parent).resolve()
    sandbox_verifier = SandboxVerifier(repository_root, use_container=sandbox_use_container)

    def _query_prom_rate(service_or_metric: str) -> float:
        try:
            res = client.query_metrics(metric_name="http_requests_total")
            if isinstance(res, dict) and "data" in res:
                data = res.get("data", {})
                results = data.get("result", [])
                total = 0.0
                errors = 0.0
                for r in results:
                    metric = r.get("metric", {})
                    status = str(metric.get("status", "200"))
                    values = r.get("values", []) or [r.get("value", [0, 0])]
                    if values:
                        val = float(values[-1][1]) if len(values[-1]) > 1 else 0.0
                        total += val
                        if status.startswith("5"):
                            errors += val
                if total > 0:
                    return round(errors / total, 4)
        except Exception:
            pass
        return 0.15

    full_verifier = FullVerifier(
        repository_root,
        use_container=sandbox_use_container,
        metrics_query_fn=_query_prom_rate,
    )

    @app.get("/health")
    def health():
        return {"status": "ok", "app": "nightshift-platform-api", "mode": mode}

    class SandboxVerifyRequest(BaseModel):
        incident_id: str = Field(..., min_length=1, max_length=128)
        fault_id: str = Field(..., pattern=r"^fault_00[1-5]_[a-z0-9_]+$")
        patch: str

    @app.post("/verify/sandbox")
    def verify_sandbox(req: SandboxVerifyRequest):
        """Apply a candidate patch in a disposable worktree and replay its fault."""
        fixture_dir = repository_root / "faults" / "catalog" / req.fault_id
        manifest_path = fixture_dir / "manifest.yaml"
        if not manifest_path.is_file():
            raise HTTPException(status_code=404, detail="Unknown Day 4 code fault")
        # The five checked-in code fixtures target one service file each.
        service_by_fault = {
            "fault_001_bad_deploy": "orders",
            "fault_002_off_by_one": "orders",
            "fault_003_wrong_status_code": "payments",
            "fault_004_bad_parsing": "gateway",
            "fault_005_unhandled_exception": "orders",
        }
        service = service_by_fault.get(req.fault_id)
        if service is None:
            raise HTTPException(status_code=404, detail="Fault is not in the Day 4 code set")
        target_file = f"target-app/services/{service}/app.py"
        reproduction_command = [
            "python", "tests/verifier/reproduce.py", req.fault_id,
        ]
        test_command = [
            "python", "-m", "pytest", "-q",
            "tests/verifier/test_reproductions.py::TestDay4Reproductions::test_"
            + req.fault_id,
        ]
        result = sandbox_verifier.verify(
            req.incident_id,
            req.patch,
            target_file=target_file,
            faulty_file=f"faults/catalog/{req.fault_id}/buggy_app.py",
            reproduction_command=reproduction_command,
        )
        return {
            **result.verification.model_dump(),
            "accepted": result.accepted,
            "error": result.error,
            "unit_test_output": result.unit_test_output,
            "reproduction_output": result.reproduction_output,
        }

    class VerifyRequest(BaseModel):
        incident_id: str = Field(..., min_length=1, max_length=128)
        fault_id: str = Field(..., pattern=r"^fault_00[1-5]_[a-z0-9_]+$")
        patch: str
        simulated_canary_healthy: Optional[bool] = None
        post_promotion_error_rate: Optional[float] = None

    @app.post("/verify")
    def verify_fix(req: VerifyRequest):
        """Single unified verification endpoint (Sandbox, Canary, Recovery) returning full VerificationResult."""
        fixture_dir = repository_root / "faults" / "catalog" / req.fault_id
        manifest_path = fixture_dir / "manifest.yaml"
        if not manifest_path.is_file():
            raise HTTPException(status_code=404, detail="Unknown Day 4/5 code fault")

        res = full_verifier.verify(
            incident_id=req.incident_id,
            fault_id=req.fault_id,
            patch=req.patch,
            simulated_canary_healthy=req.simulated_canary_healthy,
            post_promotion_error_rate=req.post_promotion_error_rate,
        )
        return res.model_dump()

    # Tool 1: Query Logs (supports both GET and POST)
    @app.get("/logs/query")
    def get_logs(
        service: Optional[str] = Query(None),
        start: Optional[str] = Query(None),
        end: Optional[str] = Query(None),
        level: Optional[str] = Query(None),
        trace_id: Optional[str] = Query(None),
        limit: int = Query(100),
        text: Optional[str] = Query(None),
    ):
        if hasattr(client, "query_logs") and "text" in client.query_logs.__code__.co_varnames:
            return client.query_logs(
                service=service, start=start, end=end, level=level, trace_id=trace_id, limit=limit, text=text
            )
        return client.query_logs(
            service=service, start=start, end=end, level=level, trace_id=trace_id, limit=limit
        )

    @app.post("/logs/query")
    def post_logs(req: LogQueryRequest):
        if hasattr(client, "query_logs") and "text" in client.query_logs.__code__.co_varnames:
            return client.query_logs(
                service=req.service,
                start=req.start,
                end=req.end,
                level=req.level,
                trace_id=req.trace_id,
                limit=req.limit,
                text=req.text,
            )
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


# Default ASGI app instance running in real mode
app = create_platform_api_app(mode="real")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("platform_api.app:app", host="127.0.0.1", port=8000, reload=True)
