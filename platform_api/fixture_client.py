"""Fixture-backed PlatformClient implementation.

Enables Person B and automated tests to run entirely offline against
recorded incident fixture bundles without requiring running services or Docker.
"""

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from contracts import load_fixture_bundle
from contracts.models import FixProposal, FixProposalReceipt
from platform_api.client import PlatformClient


class FixtureClient(PlatformClient):
    """Offline implementation of PlatformClient using recorded fixture data."""

    def __init__(
        self,
        fixture_bundle: str = "fault_001_bad_deploy",
        fixture_path: Optional[Union[str, Path]] = None,
    ):
        self.bundle_name = fixture_bundle
        if fixture_path is not None:
            import json
            p = Path(fixture_path)
            self.bundle: Dict[str, Any] = {"name": p.name, "path": str(p)}
            for key in ["incident", "logs", "metrics", "changes", "service_map", "past_incidents", "repo_snapshot", "ground_truth"]:
                f = p / f"{key}.json"
                if f.exists():
                    with open(f, "r", encoding="utf-8") as fp:
                        self.bundle[key] = json.load(fp)
        else:
            self.bundle = load_fixture_bundle(fixture_bundle)

        self.submitted_proposals: List[Dict[str, Any]] = []

    def get_incident(self) -> Dict[str, Any]:
        """Convenience method returning the incident under investigation."""
        return self.bundle.get("incident", {})

    def query_logs(
        self,
        service: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        level: Optional[str] = None,
        trace_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        logs = self.bundle.get("logs", [])
        filtered = []

        for log in logs:
            if service and log.get("service") != service:
                continue
            if level and log.get("level", "").upper() != level.upper():
                continue
            if trace_id and log.get("trace_id") != trace_id:
                continue
            filtered.append(log)

        return filtered[:limit]

    def query_metrics(
        self,
        metric_name: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        step: str = "15s",
    ) -> Dict[str, Any]:
        metrics = self.bundle.get("metrics", {})
        if not metrics or "data" not in metrics:
            return {"status": "success", "data": {"resultType": "matrix", "result": []}}

        results = metrics.get("data", {}).get("result", [])
        if metric_name and metric_name != "*":
            matched = [
                r for r in results
                if r.get("metric", {}).get("__name__") == metric_name
            ]
            if matched:
                return {
                    "status": "success",
                    "data": {"resultType": "matrix", "result": matched},
                }

        return metrics

    def list_changes(
        self,
        service: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        changes = self.bundle.get("changes", [])
        if service:
            changes = [c for c in changes if c.get("service") == service]
        return changes[:limit]

    def git_log(
        self,
        n: int = 10,
        path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        repo = self.bundle.get("repo_snapshot", {})
        commits = repo.get("commits", [])
        return commits[:n]

    def git_diff(
        self,
        commit_a: str,
        commit_b: Optional[str] = None,
        path: Optional[str] = None,
    ) -> str:
        repo = self.bundle.get("repo_snapshot", {})
        diffs = repo.get("diffs", {})

        # Direct commit key lookup
        if commit_a in diffs:
            return diffs[commit_a]

        # Key format: commit_a..commit_b
        if commit_b:
            key = f"{commit_a}..{commit_b}"
            if key in diffs:
                return diffs[key]

        # Default fallback to first available diff if searching HEAD
        if diffs:
            for k, v in diffs.items():
                if commit_a in k or "HEAD" in commit_a:
                    return v
            return next(iter(diffs.values()))

        return ""

    def read_file(
        self,
        path: str,
        ref: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        repo = self.bundle.get("repo_snapshot", {})
        files = repo.get("files", {})

        # Normalize path
        normalized_path = path.replace("\\", "/")
        content = None
        for file_key, file_content in files.items():
            if file_key.replace("\\", "/").endswith(normalized_path) or normalized_path.endswith(file_key.replace("\\", "/")):
                content = file_content
                break

        if content is None:
            # Fallback to local file on disk if path exists relative to repo
            from pathlib import Path
            candidate = Path(path)
            if candidate.exists() and candidate.is_file():
                content = candidate.read_text(encoding="utf-8")
            else:
                return ""

        if start_line is not None or end_line is not None:
            lines = content.splitlines(keepends=True)
            s = (start_line - 1) if (start_line and start_line > 0) else 0
            e = end_line if (end_line and end_line > 0) else len(lines)
            return "".join(lines[s:e])

        return content

    def service_map(self) -> Dict[str, Any]:
        return self.bundle.get("service_map", {})

    def search_past_incidents(
        self,
        query: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        incidents = self.bundle.get("past_incidents", [])
        if not query:
            return incidents[:limit]

        tokens = query.lower().split()
        scored: List[tuple] = []
        for inc in incidents:
            score = 0
            text = f"{inc.get('title', '')} {inc.get('root_cause', '')} {inc.get('resolution', '')}".lower()
            for token in tokens:
                if token in text:
                    score += 1
            scored.append((score, inc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [inc for _, inc in scored][:limit]

    def propose_fix(
        self,
        proposal: Union[FixProposal, Dict[str, Any]],
    ) -> Dict[str, Any]:
        if isinstance(proposal, dict):
            prop_obj = FixProposal(**proposal)
        else:
            prop_obj = proposal

        receipt = FixProposalReceipt(
            status="accepted",
            proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
            risk_tier=prop_obj.risk_tier,
            message=f"Fix proposal ({prop_obj.type}) accepted for verification on {prop_obj.target_service}.",
            target_service=prop_obj.target_service,
        )
        data = receipt.model_dump()
        self.submitted_proposals.append({
            "proposal": prop_obj.model_dump(),
            "receipt": data,
        })
        return data
