"""Cryptographically tamper-evident, append-only audit logger.

Owner: Person B (Brain & Trust)
Architecture Section 6 & Day 5 Task B4:
- Records every decision: who, what, why, evidence IDs, risk tier, incident ID
- Maintains an append-only JSONL log with a cryptographic SHA-256 hash chain
- Guarantees every executed action has a verifiable entry
- Tamper detection: modifying, deleting, or inserting a line is immediately detectable via the hash chain
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("safety.audit")

GENESIS_HASH = "0" * 64


class AuditIntegrityError(ValueError):
    """Raised when tampering is detected in the append-only audit log."""


@dataclass
class AuditEntry:
    """A tamper-evident audit log record."""
    sequence: int
    timestamp: str  # ISO-8601 UTC
    who: str        # e.g., "agent:autonomous", "operator:alice", "verifier:autorollback"
    what: str       # e.g., "rollback_deploy", "apply_patch", "revert_config"
    why: str        # Rationale or diagnosis justifying the decision
    evidence_ids: List[str]  # e.g., ["ev_log_001", "ev_met_002"]
    incident_id: str
    target_service: str = "orders"
    risk_tier: str = "T1"
    status: str = "EXECUTED"  # EXECUTED, REJECTED, APPROVED, ESCALATED
    metadata: Dict[str, Any] = field(default_factory=dict)
    prev_hash: str = GENESIS_HASH
    entry_hash: str = ""

    def payload_dict(self) -> Dict[str, Any]:
        """Dictionary of entry fields hashed into entry_hash (excluding entry_hash itself)."""
        return {
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "who": self.who,
            "what": self.what,
            "why": self.why,
            "evidence_ids": sorted(self.evidence_ids),
            "incident_id": self.incident_id,
            "target_service": self.target_service,
            "risk_tier": self.risk_tier,
            "status": self.status,
            "metadata": self.metadata,
            "prev_hash": self.prev_hash,
        }

    def compute_hash(self) -> str:
        """Compute the deterministic SHA-256 hash of this entry."""
        payload_bytes = json.dumps(self.payload_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload_bytes).hexdigest()

    def to_json(self) -> str:
        """Serialize entry as canonical single-line JSON."""
        d = asdict(self)
        return json.dumps(d, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuditEntry:
        """Construct AuditEntry from dictionary."""
        return cls(
            sequence=int(data["sequence"]),
            timestamp=str(data["timestamp"]),
            who=str(data["who"]),
            what=str(data["what"]),
            why=str(data["why"]),
            evidence_ids=list(data.get("evidence_ids", [])),
            incident_id=str(data["incident_id"]),
            target_service=str(data.get("target_service", "orders")),
            risk_tier=str(data.get("risk_tier", "T1")),
            status=str(data.get("status", "EXECUTED")),
            metadata=dict(data.get("metadata", {})),
            prev_hash=str(data.get("prev_hash", GENESIS_HASH)),
            entry_hash=str(data.get("entry_hash", "")),
        )


class AuditLogger:
    """Manages append-only file persistence and verification for the audit hash chain."""

    def __init__(self, log_path: Union[str, Path]) -> None:
        self.log_path = Path(log_path).resolve()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash: str = GENESIS_HASH
        self._last_sequence: int = -1
        self._load_tail()

    def _load_tail(self) -> None:
        """Read the last entry from the log file to initialize the next link in the chain."""
        if not self.log_path.is_file():
            self._last_hash = GENESIS_HASH
            self._last_sequence = -1
            return

        last_entry: Optional[AuditEntry] = None
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                data = json.loads(line_str)
                last_entry = AuditEntry.from_dict(data)

        if last_entry is not None:
            self._last_hash = last_entry.entry_hash
            self._last_sequence = last_entry.sequence
        else:
            self._last_hash = GENESIS_HASH
            self._last_sequence = -1

    def log_decision(
        self,
        who: str,
        what: str,
        why: str,
        evidence_ids: List[str],
        incident_id: str,
        target_service: str = "orders",
        risk_tier: str = "T1",
        status: str = "EXECUTED",
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None,
    ) -> AuditEntry:
        """Append a decision record to the audit log, chaining its cryptographic hash."""
        now_ts = timestamp or datetime.now(timezone.utc).isoformat()
        next_seq = self._last_sequence + 1
        prev_h = self._last_hash

        entry = AuditEntry(
            sequence=next_seq,
            timestamp=now_ts,
            who=who,
            what=what,
            why=why,
            evidence_ids=list(evidence_ids),
            incident_id=incident_id,
            target_service=target_service,
            risk_tier=risk_tier,
            status=status,
            metadata=dict(metadata or {}),
            prev_hash=prev_h,
        )
        entry.entry_hash = entry.compute_hash()

        # Append-only write
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")

        self._last_hash = entry.entry_hash
        self._last_sequence = entry.sequence
        return entry

    def read_entries(self) -> List[AuditEntry]:
        """Read all entries from the log file."""
        if not self.log_path.is_file():
            return []
        entries: list[AuditEntry] = []
        with open(self.log_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if line_str:
                    entries.append(AuditEntry.from_dict(json.loads(line_str)))
        return entries

    def verify_integrity(self) -> Tuple[bool, str]:
        """Verify the integrity of the audit log hash chain.

        Returns (is_valid, report_message).
        Detects edited, deleted, or inserted lines.
        """
        if not self.log_path.is_file():
            return True, "Audit log is empty (no file)"

        expected_prev = GENESIS_HASH
        expected_seq = 0

        with open(self.log_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, 1):
                line_str = line.strip()
                if not line_str:
                    continue

                try:
                    data = json.loads(line_str)
                    entry = AuditEntry.from_dict(data)
                except Exception as exc:
                    return False, f"Tampering detected at line {line_idx}: invalid JSON ({exc})"

                # Check sequence continuity
                if entry.sequence != expected_seq:
                    return False, (
                        f"Tampering detected at line {line_idx}: non-contiguous sequence "
                        f"(got {entry.sequence}, expected {expected_seq}); possible deleted or inserted line"
                    )

                # Check prev_hash matches previous link
                if entry.prev_hash != expected_prev:
                    return False, (
                        f"Tampering detected at line {line_idx} (seq {entry.sequence}): "
                        f"broken hash chain! prev_hash '{entry.prev_hash}' does not match "
                        f"expected '{expected_prev}'"
                    )

                # Recompute hash to detect any content editing
                recomputed_hash = entry.compute_hash()
                if entry.entry_hash != recomputed_hash:
                    return False, (
                        f"Tampering detected at line {line_idx} (seq {entry.sequence}): "
                        f"content was edited! Stored hash '{entry.entry_hash}' != "
                        f"recomputed '{recomputed_hash}'"
                    )

                expected_prev = entry.entry_hash
                expected_seq += 1

        return True, f"Audit log verified: {expected_seq} entries intact with unbroken hash chain"

    def filter_entries(
        self,
        incident_id: Optional[str] = None,
        who: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[AuditEntry]:
        """Filter entries by incident, actor, or status."""
        entries = self.read_entries()
        filtered = entries
        if incident_id:
            filtered = [e for e in filtered if e.incident_id == incident_id]
        if who:
            filtered = [e for e in filtered if e.who == who]
        if status:
            filtered = [e for e in filtered if e.status == status]
        return filtered
