"""SQLite Incident Memory Store (Day 7 Task B1).

Persists solved incidents (category, symptom signature, root cause, fix,
and evidence summary) in SQLite with automatic deduplication & merging
when duplicate incidents are saved.

Owner: Person B (Brain & Trust)
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_signature(text: str) -> str:
    """Normalize a symptom signature for deterministic deduplication."""
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return " ".join(cleaned.split())


def compute_signature_hash(category: str, service: str, symptom_signature: str) -> str:
    """Compute stable hash identifying a (category, service, symptom_signature) tuple."""
    key = f"{category.strip().lower()}|{service.strip().lower()}|{normalize_signature(symptom_signature)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


@dataclass
class IncidentMemoryRecord:
    """Stored memory entry for a resolved incident."""

    incident_id: str
    category: str
    symptom_signature: str
    cause: str
    fix: str
    evidence_summary: str
    service: str = "orders"
    fault_id: Optional[str] = None
    evidence_ids: List[str] = field(default_factory=list)
    occurrence_count: int = 1
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IncidentMemoryStore:
    """SQLite-backed memory store for solved incidents with duplicate merging."""

    def __init__(self, db_path: Union[str, Path] = ":memory:") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS incident_memories (
                incident_id TEXT PRIMARY KEY,
                signature_hash TEXT UNIQUE NOT NULL,
                fault_id TEXT,
                service TEXT NOT NULL,
                category TEXT NOT NULL,
                symptom_signature TEXT NOT NULL,
                cause TEXT NOT NULL,
                fix TEXT NOT NULL,
                evidence_summary TEXT NOT NULL,
                evidence_ids_json TEXT NOT NULL,
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _row_to_record(self, row: sqlite3.Row) -> IncidentMemoryRecord:
        return IncidentMemoryRecord(
            incident_id=row["incident_id"],
            fault_id=row["fault_id"],
            service=row["service"],
            category=row["category"],
            symptom_signature=row["symptom_signature"],
            cause=row["cause"],
            fix=row["fix"],
            evidence_summary=row["evidence_summary"],
            evidence_ids=json.loads(row["evidence_ids_json"] or "[]"),
            occurrence_count=int(row["occurrence_count"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save(self, record: IncidentMemoryRecord) -> IncidentMemoryRecord:
        """Save a memory record, merging duplicates with the same incident_id or signature."""
        sig_hash = compute_signature_hash(record.category, record.service, record.symptom_signature)
        now = _utc_now()

        existing_row = self._conn.execute(
            """
            SELECT * FROM incident_memories
            WHERE incident_id = ? OR signature_hash = ?
            LIMIT 1
            """,
            (record.incident_id, sig_hash),
        ).fetchone()

        if existing_row is not None:
            existing = self._row_to_record(existing_row)
            merged_evidence_ids = list(dict.fromkeys(existing.evidence_ids + record.evidence_ids))
            merged_count = existing.occurrence_count + max(1, record.occurrence_count)
            merged_fix = record.fix or existing.fix
            merged_cause = record.cause or existing.cause
            if record.evidence_summary and record.evidence_summary not in existing.evidence_summary:
                merged_summary = f"{existing.evidence_summary}; {record.evidence_summary}".strip("; ")
            else:
                merged_summary = existing.evidence_summary or record.evidence_summary

            self._conn.execute(
                """
                UPDATE incident_memories
                SET fault_id = COALESCE(?, fault_id),
                    cause = ?,
                    fix = ?,
                    evidence_summary = ?,
                    evidence_ids_json = ?,
                    occurrence_count = ?,
                    updated_at = ?
                WHERE incident_id = ?
                """,
                (
                    record.fault_id,
                    merged_cause,
                    merged_fix,
                    merged_summary,
                    json.dumps(merged_evidence_ids),
                    merged_count,
                    now,
                    existing.incident_id,
                ),
            )
            self._conn.commit()
            loaded = self.load(existing.incident_id)
            assert loaded is not None
            return loaded

        self._conn.execute(
            """
            INSERT INTO incident_memories (
                incident_id, signature_hash, fault_id, service, category,
                symptom_signature, cause, fix, evidence_summary,
                evidence_ids_json, occurrence_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.incident_id,
                sig_hash,
                record.fault_id,
                record.service,
                record.category,
                record.symptom_signature,
                record.cause,
                record.fix,
                record.evidence_summary,
                json.dumps(list(dict.fromkeys(record.evidence_ids))),
                max(1, record.occurrence_count),
                record.created_at or now,
                record.updated_at or now,
            ),
        )
        self._conn.commit()
        loaded = self.load(record.incident_id)
        assert loaded is not None
        return loaded

    def load(self, incident_id: str) -> Optional[IncidentMemoryRecord]:
        """Load a single memory record by incident_id."""
        row = self._conn.execute(
            "SELECT * FROM incident_memories WHERE incident_id = ?",
            (incident_id,),
        ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list_all(self) -> List[IncidentMemoryRecord]:
        """Return all stored incident memory records ordered by recency."""
        rows = self._conn.execute(
            "SELECT * FROM incident_memories ORDER BY updated_at DESC, occurrence_count DESC"
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def count(self) -> int:
        """Return total number of distinct merged incident memories."""
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM incident_memories").fetchone()
        return int(row["cnt"]) if row else 0
