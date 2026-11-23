"""PlatformClient backed by a recorded incident bundle (JSON). Same method names as the live client.

Bundle schema: {fault_id, incident, logs[], changes[], service_map{nodes,edges}, git_log[], diffs{sha: {...}}, files{path: text}}
Use it until A's FixtureClient is wired; swap freely (same interface).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.rca_time import to_epoch


class BundleClient:
    def __init__(self, bundle: dict[str, Any]):
        self.b = bundle

    @classmethod
    def from_file(cls, path: str | Path) -> "BundleClient":
        return cls(json.loads(Path(path).read_text()))

    def query_logs(self, service=None, level=None, since=None, until=None, text=None, limit=100):
        lo, hi = to_epoch(since), to_epoch(until)
        out = []
        for e in self.b.get("logs", []):
            ts = to_epoch(e["ts"])
            if service and e.get("service") != service:
                continue
            if level and str(e.get("level", "")).upper() != level.upper():
                continue
            if lo is not None and ts < lo or hi is not None and ts > hi:
                continue
            if text and text.lower() not in str(e.get("message", "")).lower():
                continue
            out.append(e)
        return {"entries": out[: int(limit)]}

    def query_metrics(self, query=None, start=None, end=None):
        return self.b.get("metrics", {}).get(query or "", {"series": []})

    def list_changes(self, since=None, until=None, service=None):
        lo, hi = to_epoch(since), to_epoch(until)
        out = [c for c in self.b.get("changes", [])
               if (lo is None or c["ts"] >= lo) and (hi is None or c["ts"] <= hi) and (not service or c["service"] == service)]
        return {"changes": out}

    def git_log(self, path=None, since=None, until=None, n=20):
        return {"commits": self.b.get("git_log", [])[: int(n)]}

    def git_diff(self, commit=None, base=None, head=None, path=None):
        return self.b.get("diffs", {}).get(commit or "", {"diff": "", "files": []})

    def read_file(self, path, ref=None, start_line=None, end_line=None):
        files = self.b.get("files", {})
        if path not in files:
            raise FileNotFoundError(path)
        return {"path": path, "content": files[path]}

    def service_map(self):
        return self.b.get("service_map", {"nodes": [], "edges": []})

    def search_past_incidents(self, query=None):
        return {"results": []}
