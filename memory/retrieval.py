"""Past Incident Similarity Retrieval (Day 7 Task B2).

Implements keyword + category + service similarity scoring over `IncidentMemoryStore`.
Repeated incidents retrieve their predecessor at rank 1; unrelated incidents score
below `threshold` and return no false matches.

Owner: Person B (Brain & Trust)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from memory.store import IncidentMemoryRecord, IncidentMemoryStore

STOPWORDS: Set[str] = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "that", "the", "to", "was",
    "were", "with", "when", "after", "before", "into", "service",
    "error", "failed", "failure", "incident", "alert",
}


def tokenize(text: str) -> Set[str]:
    """Tokenize text into normalized meaningful keywords."""
    words = re.findall(r"[a-z0-9_]+", (text or "").lower())
    tokens: Set[str] = set()
    for w in words:
        for part in w.split("_"):
            if len(part) >= 2 and part not in STOPWORDS:
                tokens.add(part)
        if len(w) >= 2 and w not in STOPWORDS:
            tokens.add(w)
    return tokens


def score_similarity(
    query: str,
    record: IncidentMemoryRecord,
    *,
    category: Optional[str] = None,
    service: Optional[str] = None,
) -> float:
    """Compute similarity score in [0.0, 1.0] using keyword overlap + category + service."""
    q_tokens = tokenize(query)
    if not q_tokens:
        return 0.0

    # Build weighted document token sets
    sym_tokens = tokenize(record.symptom_signature)
    cause_tokens = tokenize(record.cause)
    fix_tokens = tokenize(record.fix)
    ev_tokens = tokenize(record.evidence_summary)
    all_doc_tokens = sym_tokens | cause_tokens | fix_tokens | ev_tokens | tokenize(record.service)

    if not all_doc_tokens:
        return 0.0

    overlap = q_tokens & all_doc_tokens
    if not overlap:
        return 0.0

    # Recall over query + Jaccard blend
    query_recall = len(overlap) / len(q_tokens)
    jaccard = len(overlap) / len(q_tokens | all_doc_tokens)
    sym_overlap = len(q_tokens & sym_tokens) / max(1, len(q_tokens))

    score = (0.50 * query_recall) + (0.25 * jaccard) + (0.25 * sym_overlap)

    if category:
        if record.category.lower() == category.strip().lower():
            score += 0.15
        else:
            score -= 0.10

    if service and record.service.lower() == service.strip().lower():
        score += 0.10

    return round(max(0.0, min(1.0, score)), 4)


def search_past_incidents(
    store: IncidentMemoryStore,
    query: str,
    *,
    category: Optional[str] = None,
    service: Optional[str] = None,
    threshold: float = 0.25,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Retrieve matching past incidents ranked by similarity score above `threshold`."""
    candidates: List[tuple[float, int, IncidentMemoryRecord]] = []

    for rec in store.list_all():
        sim = score_similarity(query, rec, category=category, service=service)
        if sim >= threshold:
            candidates.append((sim, rec.occurrence_count, rec))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

    results: List[Dict[str, Any]] = []
    for sim, _, rec in candidates[:limit]:
        results.append({
            "incident_id": rec.incident_id,
            "fault_id": rec.fault_id,
            "score": sim,
            "category": rec.category,
            "service": rec.service,
            "symptom_signature": rec.symptom_signature,
            "cause": rec.cause,
            "fix": rec.fix,
            "evidence_summary": rec.evidence_summary,
            "evidence_ids": rec.evidence_ids,
            "occurrence_count": rec.occurrence_count,
        })
    return results
