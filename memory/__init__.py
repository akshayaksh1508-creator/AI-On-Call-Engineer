"""memory component package.

Owner: Person B (Brain & Trust)
Provides SQLite-backed solved incident storage and similarity retrieval.
"""

from memory.retrieval import score_similarity, search_past_incidents
from memory.store import (
    IncidentMemoryRecord,
    IncidentMemoryStore,
    compute_signature_hash,
    normalize_signature,
)

__all__ = [
    "IncidentMemoryRecord",
    "IncidentMemoryStore",
    "compute_signature_hash",
    "normalize_signature",
    "score_similarity",
    "search_past_incidents",
]
