"""HTTP and In-Process Client for Stub Platform API.

Implements PlatformClient by calling the REST endpoints of StubPlatformAPI.
Can run against an active HTTP server or in-process via Starlette TestClient.
"""

from typing import Any, Dict, List, Optional, Union
from starlette.testclient import TestClient

from contracts.models import FixProposal
from platform_api.client import PlatformClient
from platform_api.stub_app import create_platform_api_app, app as default_app


class StubClient(PlatformClient):
    """PlatformClient implementation communicating with StubPlatformAPI."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        fixture_bundle: str = "fault_001_bad_deploy",
    ):
        self.base_url = base_url
        if base_url:
            self._client = None
        else:
            # In-process TestClient
            app_instance = create_platform_api_app(fixture_bundle=fixture_bundle)
            self._client = TestClient(app_instance)

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        clean_params = {k: v for k, v in params.items() if v is not None} if params else None
        if self._client:
            resp = self._client.get(path, params=clean_params)
            resp.raise_for_status()
            return resp.json()
        else:
            import urllib.parse
            import urllib.request
            import json

            url = f"{self.base_url.rstrip('/')}{path}"
            if clean_params:
                query_str = urllib.parse.urlencode(clean_params)
                url = f"{url}?{query_str}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode("utf-8"))

    def _post(self, path: str, json_data: Dict[str, Any]) -> Any:
        if self._client:
            resp = self._client.post(path, json=json_data)
            resp.raise_for_status()
            return resp.json()
        else:
            import urllib.request
            import json

            url = f"{self.base_url.rstrip('/')}{path}"
            data_bytes = json.dumps(json_data).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data_bytes,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode("utf-8"))

    def query_logs(
        self,
        service: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        level: Optional[str] = None,
        trace_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        params = {
            "service": service,
            "start": start,
            "end": end,
            "level": level,
            "trace_id": trace_id,
            "limit": limit,
        }
        return self._get("/logs/query", params=params)

    def query_metrics(
        self,
        metric_name: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        step: str = "15s",
    ) -> Dict[str, Any]:
        params = {
            "metric_name": metric_name,
            "start": start,
            "end": end,
            "step": step,
        }
        return self._get("/metrics/query", params=params)

    def list_changes(
        self,
        service: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        params = {"service": service, "since": since, "limit": limit}
        return self._get("/changes", params=params)

    def git_log(
        self,
        n: int = 10,
        path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params = {"n": n, "path": path}
        return self._get("/repo/log", params=params)

    def git_diff(
        self,
        commit_a: str,
        commit_b: Optional[str] = None,
        path: Optional[str] = None,
    ) -> str:
        params = {"commit_a": commit_a, "commit_b": commit_b, "path": path}
        res = self._get("/repo/diff", params=params)
        return res.get("diff", "")

    def read_file(
        self,
        path: str,
        ref: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        params = {"path": path, "ref": ref, "start_line": start_line, "end_line": end_line}
        res = self._get("/repo/show", params=params)
        return res.get("content", "")

    def service_map(self) -> Dict[str, Any]:
        return self._get("/service-map")

    def search_past_incidents(
        self,
        query: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        params = {"query": query, "limit": limit}
        return self._get("/memory/search", params=params)

    def propose_fix(
        self,
        proposal: Union[FixProposal, Dict[str, Any]],
    ) -> Dict[str, Any]:
        if hasattr(proposal, "model_dump"):
            payload = proposal.model_dump()
        else:
            payload = proposal
        return self._post("/fix/propose", json_data=payload)
