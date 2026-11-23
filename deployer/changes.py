"""Append-only change-event feed (deploys, rollbacks, config changes).

Owner: Person A.  Every deploy / rollback / config change writes one JSON line.
The agent reads this feed through the Platform API tool `list_changes`.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ChangeEvent:
    id: str
    ts: float
    ts_iso: str
    type: str  # deploy | rollback | config | deploy_failed
    service: str
    from_ref: str | None
    to_ref: str | None
    author: str
    message: str
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChangeLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def emit(
        self,
        type: str,
        service: str,
        from_ref: str | None,
        to_ref: str | None,
        author: str = "system",
        message: str = "",
        meta: dict[str, Any] | None = None,
        ts: float | None = None,
    ) -> ChangeEvent:
        ts = time.time() if ts is None else float(ts)
        ev = ChangeEvent(
            id="chg-" + uuid.uuid4().hex[:10],
            ts=ts,
            ts_iso=datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            type=type,
            service=service,
            from_ref=from_ref,
            to_ref=to_ref,
            author=author,
            message=message,
            meta=meta or {},
        )
        with self._lock:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev.to_dict()) + "\n")
        return ev

    def list(
        self,
        since: float | None = None,
        until: float | None = None,
        service: str | None = None,
        type: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # tolerate a half-written line
        out = [
            e
            for e in events
            if (since is None or e["ts"] >= since)
            and (until is None or e["ts"] <= until)
            and (service is None or e["service"] == service)
            and (type is None or e["type"] == type)
        ]
        out.sort(key=lambda e: e["ts"])
        if limit:
            out = out[-limit:]
        return out
