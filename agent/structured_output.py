"""Structured Output Parser, Evidence ID Generator, and Schema Validator.

Owner: Person B (Brain & Trust)
Fulfills Day 2 Task B3:
1. EvidenceIdGenerator for systematic, conflict-free evidence tracking.
2. Robust JSON extraction and self-healing repair (markdown blocks, quotes, Python literals, trailing commas, unclosed brackets).
3. Schema validation against contracts.models (Hypothesis, Evidence).
4. Evidence cross-referencing and strict claim citation verification:
   - Any hypothesis without evidence IDs is flagged as a [GUESS].
   - Any hypothesis citing an unknown evidence ID is flagged as [UNREFERENCED].
   - Any factual claim without an evidence ID is flagged in uncited_claims.
5. Normalization for categories, confidence scales (percentages/floats), and evidence types.
6. Targeted repair prompt generator for LLM one-turn recovery.
"""

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional, Set, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contracts.models import Evidence, Hypothesis

logger = logging.getLogger("nightshift.agent.structured_output")


class EvidenceIdGenerator:
    """Generates and tracks unique, collision-free evidence identifiers."""

    PREFIX_MAP = {
        "log": "ev_log",
        "metric": "ev_metric",
        "commit": "ev_commit",
        "config": "ev_config",
        "past_incident": "ev_past",
    }

    def __init__(self, default_prefix: str = "ev"):
        self.default_prefix = default_prefix
        self._counts: Dict[str, int] = {}
        self._registered_ids: Set[str] = set()

    def register(self, evidence_id: str) -> None:
        """Register an existing ID to prevent future collisions."""
        if not evidence_id:
            return
        clean_id = evidence_id.strip()
        self._registered_ids.add(clean_id)
        # If ID matches prefix_number, advance counter
        match = re.match(r"^([a-zA-Z_]+)_(\d+)$", clean_id)
        if match:
            prefix, num_str = match.groups()
            num = int(num_str)
            if num >= self._counts.get(prefix, 0):
                self._counts[prefix] = num

    def generate(self, evidence_type: str = "evidence") -> str:
        """Generate a new unique evidence ID for the given evidence type."""
        prefix = self.PREFIX_MAP.get(evidence_type.lower(), f"{self.default_prefix}_{evidence_type.lower()}")
        # Sanitize prefix
        prefix = re.sub(r"[^a-zA-Z0-9_]", "_", prefix)

        while True:
            self._counts[prefix] = self._counts.get(prefix, 0) + 1
            candidate = f"{prefix}_{self._counts[prefix]:03d}"
            if candidate not in self._registered_ids:
                self._registered_ids.add(candidate)
                return candidate

    def is_registered(self, evidence_id: str) -> bool:
        """Check if an evidence ID has been registered."""
        return evidence_id in self._registered_ids

    def get_registered_ids(self) -> Set[str]:
        """Return a copy of all registered evidence IDs."""
        return set(self._registered_ids)

    def reset(self) -> None:
        """Reset counters and registered IDs."""
        self._counts.clear()
        self._registered_ids.clear()


class StructuredDiagnosis(BaseModel):
    """Full schema for agent diagnosis output according to Section 7 & Task B3."""
    model_config = ConfigDict(extra="ignore")

    investigation_summary: str = Field(
        default="",
        description="Concise chronological summary of diagnostic findings and reasoning."
    )
    evidence: List[Evidence] = Field(
        default_factory=list,
        description="Extracted telemetry and empirical artifacts supporting hypotheses."
    )
    hypotheses: List[Hypothesis] = Field(
        default_factory=list,
        description="Ranked root-cause hypotheses ordered by calibrated confidence."
    )
    uncited_claims: List[str] = Field(
        default_factory=list,
        description="Claims lacking evidence IDs or citing missing evidence."
    )
    recommended_action: Literal["propose_fix", "escalate", "investigate_further"] = Field(
        default="propose_fix",
        description="Next operational action based on diagnostic findings."
    )
    escalation_reason: Optional[str] = Field(
        default=None,
        description="Reason for human escalation if confidence is low or action is escalate."
    )


# Normalization mappings
CATEGORY_MAPPINGS: Dict[str, Literal["code", "config", "resource", "cross_service", "dependency", "unknown"]] = {
    "code": "code",
    "bug": "code",
    "software": "code",
    "logic": "code",
    "syntax": "code",
    "exception": "code",
    "config": "config",
    "configuration": "config",
    "env": "config",
    "environment": "config",
    "setting": "config",
    "settings": "config",
    "flag": "config",
    "resource": "resource",
    "resources": "resource",
    "cpu": "resource",
    "memory": "resource",
    "disk": "resource",
    "leak": "resource",
    "oom": "resource",
    "saturation": "resource",
    "cross_service": "cross_service",
    "cross-service": "cross_service",
    "cross service": "cross_service",
    "upstream": "cross_service",
    "downstream": "cross_service",
    "cascading": "cross_service",
    "dependency": "dependency",
    "database": "dependency",
    "postgres": "dependency",
    "db": "dependency",
    "third_party": "dependency",
    "third-party": "dependency",
    "external": "dependency",
    "network": "dependency",
    "unknown": "unknown",
}

EVIDENCE_TYPE_MAPPINGS: Dict[str, Literal["log", "metric", "commit", "config", "past_incident"]] = {
    "log": "log",
    "logs": "log",
    "logging": "log",
    "trace": "log",
    "metric": "metric",
    "metrics": "metric",
    "telemetry": "metric",
    "prometheus": "metric",
    "commit": "commit",
    "commits": "commit",
    "git": "commit",
    "git_log": "commit",
    "diff": "commit",
    "patch": "commit",
    "code": "commit",
    "config": "config",
    "configuration": "config",
    "env": "config",
    "setting": "config",
    "past_incident": "past_incident",
    "past": "past_incident",
    "incident": "past_incident",
    "memory": "past_incident",
    "history": "past_incident",
}


def repair_json_string(text: str) -> str:
    """Repair common LLM JSON syntax issues using deterministic heuristics."""
    text = text.strip()

    # 1. Strip markdown code fences (```json ... ``` or ``` ... ```)
    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced_match:
        text = fenced_match.group(1).strip()
    else:
        # Check if text starts with ```json
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```"):
                end_idx = len(lines)
                if lines[-1].strip() == "```":
                    end_idx = -1
                text = "\n".join(lines[1:end_idx]).strip()

    # 2. Extract outermost matching curly braces
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace >= first_brace:
        text = text[first_brace : last_brace + 1]

    # 3. Replace Python constants: True, False, None -> true, false, null
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)

    # 4. Remove trailing commas before closing braces/brackets
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # 5. Handle single-quoted keys and string values safely
    # If standard json.loads fails, try single-quote replacement
    try:
        json.loads(text)
        return text
    except Exception:
        pass

    repaired = _replace_single_quotes(text)
    try:
        json.loads(repaired)
        return repaired
    except Exception:
        pass

    # 6. Check for unclosed brackets/braces (truncation repair)
    repaired_balanced = _balance_brackets(repaired)
    try:
        json.loads(repaired_balanced)
        return repaired_balanced
    except Exception:
        pass

    # 7. Check balanced on original text
    original_balanced = _balance_brackets(text)
    try:
        json.loads(original_balanced)
        return original_balanced
    except Exception:
        pass

    return text


def _replace_single_quotes(text: str) -> str:
    """Convert single-quoted JSON properties and string values to valid double quotes."""
    # Pattern to match 'key': or 'string value'
    # Handles escaped quotes and apostrophes inside strings
    result = []
    in_single_quote = False
    in_double_quote = False
    i = 0
    n = len(text)

    while i < n:
        c = text[i]

        if c == "\\" and i + 1 < n:
            result.append(c)
            result.append(text[i + 1])
            i += 2
            continue

        if c == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            result.append(c)
            i += 1
            continue

        if c == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            result.append('"')
            i += 1
            continue

        result.append(c)
        i += 1

    return "".join(result)


def _balance_brackets(text: str) -> str:
    """Append missing closing braces and brackets to truncated JSON structures."""
    stack = []
    in_string = False
    escape = False

    for c in text:
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if c in ("{", "["):
            stack.append(c)
        elif c == "}":
            if stack and stack[-1] == "{":
                stack.pop()
        elif c == "]":
            if stack and stack[-1] == "[":
                stack.pop()

    closers = []
    while stack:
        opener = stack.pop()
        closers.append("}" if opener == "{" else "]")

    # Before appending closers, strip any trailing comma
    cleaned = text.rstrip()
    if cleaned.endswith(","):
        cleaned = cleaned[:-1]

    return cleaned + "".join(closers)


def extract_and_parse_json(text: str) -> Tuple[Dict[str, Any], bool]:
    """Extract and parse a JSON dictionary from LLM output with self-healing repairs.

    Returns:
        (data_dict, was_repaired)
    """
    text_clean = text.strip()
    was_repaired = False

    # First attempt: direct load
    try:
        data = json.loads(text_clean)
        if isinstance(data, dict):
            # Check if wrapped in {"data": ...} or {"result": ...}
            for wrap_key in ("data", "result", "response", "diagnosis"):
                if wrap_key in data and isinstance(data[wrap_key], dict) and len(data) == 1:
                    return data[wrap_key], True
            return data, False
    except Exception:
        pass

    # Second attempt: repair json string
    repaired = repair_json_string(text_clean)
    was_repaired = True

    try:
        data = json.loads(repaired)
        if isinstance(data, dict):
            for wrap_key in ("data", "result", "response", "diagnosis"):
                if wrap_key in data and isinstance(data[wrap_key], dict) and len(data) == 1:
                    return data[wrap_key], True
            return data, True
    except Exception as e:
        raise ValueError(
            f"Failed to parse or repair JSON from agent response: {e}\nRaw excerpt:\n{text[:300]}"
        ) from e

    raise ValueError(f"Extracted JSON is not an object/dict: {type(data)}")


def normalize_confidence(value: Any) -> float:
    """Normalize confidence to a float bounded between 0.0 and 1.0."""
    if value is None:
        return 0.5

    is_explicit_percent = False
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.endswith("%"):
            is_explicit_percent = True
            cleaned = cleaned.rstrip("%").strip()
        try:
            val_float = float(cleaned)
        except ValueError:
            low = value.lower()
            if "high" in low:
                return 0.9
            elif "med" in low:
                return 0.6
            elif "low" in low:
                return 0.3
            return 0.5
    elif isinstance(value, (int, float)):
        val_float = float(value)
    else:
        return 0.5

    # If explicitly percentage or >= 5.0 (e.g. 50, 85, 95.0), scale down by 100
    if is_explicit_percent or val_float >= 5.0:
        val_float = val_float / 100.0

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, round(val_float, 4)))


def normalize_category(value: Any) -> Literal["code", "config", "resource", "cross_service", "dependency", "unknown"]:
    """Normalize category string into one of the 6 allowed contract literals."""
    if not value or not isinstance(value, str):
        return "unknown"
    cleaned = value.strip().lower()
    return CATEGORY_MAPPINGS.get(cleaned, "unknown")


def normalize_evidence_type(value: Any) -> Literal["log", "metric", "commit", "config", "past_incident"]:
    """Normalize evidence type into one of the 5 allowed contract literals."""
    if not value or not isinstance(value, str):
        return "log"
    cleaned = value.strip().lower()
    return EVIDENCE_TYPE_MAPPINGS.get(cleaned, "log")


def validate_and_build_diagnosis(
    raw_data: Dict[str, Any],
    id_generator: Optional[EvidenceIdGenerator] = None,
) -> StructuredDiagnosis:
    """Transform, normalize, and strictly validate parsed dictionary into StructuredDiagnosis.

    Fulfills Section 7 & Day 2 Task B3 rules:
    - Every claim must cite an Evidence ID.
    - Uncited hypotheses or claims are explicitly flagged in uncited_claims as [GUESS].
    - Unreferenced evidence IDs are flagged as [UNREFERENCED].
    - Evidence IDs are generated or preserved without collisions.
    - Output hypotheses are sorted by confidence descending.
    """
    id_gen = id_generator or EvidenceIdGenerator()

    # 1. Normalize and Register Evidence items
    raw_evidence_list = raw_data.get("evidence", [])
    if isinstance(raw_evidence_list, dict):
        # Handle case where evidence was given as a dictionary
        raw_evidence_list = list(raw_evidence_list.values())
    elif not isinstance(raw_evidence_list, list):
        raw_evidence_list = []

    # First pass: register all explicitly given IDs
    for item in raw_evidence_list:
        if isinstance(item, dict) and item.get("id"):
            id_gen.register(str(item["id"]).strip())

    validated_evidence: List[Evidence] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for item in raw_evidence_list:
        if not isinstance(item, dict):
            continue

        ev_type = normalize_evidence_type(item.get("type"))
        ev_id = str(item.get("id", "")).strip()
        if not ev_id:
            ev_id = id_gen.generate(ev_type)
            item["id"] = ev_id

        # Normalize timestamp
        ts = str(item.get("ts", "")).strip() or now_iso
        ref = str(item.get("ref", "")).strip() or "telemetry/stream"
        excerpt = str(item.get("excerpt", "")).strip() or "Telemetry excerpt recorded during incident"

        try:
            ev = Evidence(
                id=ev_id,
                type=ev_type,
                ref=ref,
                excerpt=excerpt,
                ts=ts,
            )
            validated_evidence.append(ev)
        except ValidationError as ve:
            logger.warning("Evidence item failed validation: %s", ve)

    known_evidence_ids = {e.id for e in validated_evidence}

    # 2. Normalize and Validate Hypotheses
    raw_hypotheses = raw_data.get("hypotheses", [])
    if isinstance(raw_hypotheses, dict):
        raw_hypotheses = [raw_hypotheses]
    elif not isinstance(raw_hypotheses, list):
        raw_hypotheses = []

    validated_hypotheses: List[Hypothesis] = []
    uncited_claims: List[str] = []

    # Preserve any existing uncited claims in raw data
    raw_uncited = raw_data.get("uncited_claims", [])
    if isinstance(raw_uncited, list):
        for uc in raw_uncited:
            if isinstance(uc, str) and uc.strip():
                uncited_claims.append(uc.strip())

    for idx, item in enumerate(raw_hypotheses):
        if not isinstance(item, dict):
            continue

        cause = str(item.get("cause", "")).strip()
        if not cause:
            cause = f"Unspecified failure hypothesis #{idx + 1}"

        category = normalize_category(item.get("category"))
        confidence = normalize_confidence(item.get("confidence"))

        # Extract and normalize evidence_ids
        raw_eids = item.get("evidence_ids", [])
        if isinstance(raw_eids, str):
            # Split comma-separated IDs or extract IDs with regex
            raw_eids = [e.strip() for e in re.split(r"[,;\s]+", raw_eids) if e.strip()]
        elif not isinstance(raw_eids, list):
            raw_eids = []

        clean_eids = [str(e).strip() for e in raw_eids if str(e).strip()]

        # Check for citation rule: Every claim must cite an Evidence ID
        if not clean_eids:
            claim_desc = cause[:80] + ("..." if len(cause) > 80 else "")
            uncited_claims.append(
                f"[GUESS] Hypothesis '{claim_desc}' has no cited evidence IDs."
            )
        else:
            # Check if any cited evidence ID does not exist in known evidence
            for eid in clean_eids:
                if eid not in known_evidence_ids:
                    uncited_claims.append(
                        f"[UNREFERENCED] Hypothesis cites unknown evidence ID '{eid}'."
                    )

        culprit = item.get("culprit_change")
        if culprit is not None:
            culprit = str(culprit).strip() or None

        try:
            hyp = Hypothesis(
                cause=cause,
                category=category,
                confidence=confidence,
                evidence_ids=clean_eids,
                culprit_change=culprit,
            )
            validated_hypotheses.append(hyp)
        except ValidationError as ve:
            logger.warning("Hypothesis item failed validation: %s", ve)

    # Sort hypotheses by confidence descending
    validated_hypotheses.sort(key=lambda h: h.confidence, reverse=True)

    # 3. Recommended action & summary
    summary = str(raw_data.get("investigation_summary", "")).strip()
    rec_action = raw_data.get("recommended_action", "propose_fix")
    if rec_action not in ("propose_fix", "escalate", "investigate_further"):
        rec_action = "propose_fix"

    esc_reason = raw_data.get("escalation_reason")
    if esc_reason is not None:
        esc_reason = str(esc_reason).strip() or None

    # Flag if no hypotheses generated
    if not validated_hypotheses:
        uncited_claims.append("[GUESS] No root-cause hypotheses were provided in agent diagnosis.")

    return StructuredDiagnosis(
        investigation_summary=summary,
        evidence=validated_evidence,
        hypotheses=validated_hypotheses,
        uncited_claims=uncited_claims,
        recommended_action=rec_action,
        escalation_reason=esc_reason,
    )


def build_repair_prompt(error_msg: str, original_response: str) -> str:
    """Build a targeted 1-turn repair prompt for an LLM that delivered invalid output."""
    return f"""The diagnostic response you provided could not be validated against the required schema.

ERROR DETAILS:
{error_msg}

YOUR PREVIOUS RESPONSE (EXCERPT):
```
{original_response[:500]}
```

REQUIRED FORMAT:
You must respond with ONLY a single valid JSON object strictly matching this schema:
{{
  "investigation_summary": "Concise summary of findings.",
  "evidence": [
    {{
      "id": "ev_log_001",
      "type": "log",
      "ref": "target-app/orders/main.py:42",
      "excerpt": "Exact log or metric excerpt",
      "ts": "2026-11-23T10:00:00Z"
    }}
  ],
  "hypotheses": [
    {{
      "cause": "Specific root cause explanation citing [ev_log_001]",
      "category": "code",
      "confidence": 0.90,
      "evidence_ids": ["ev_log_001"],
      "culprit_change": "git_commit_sha_or_null"
    }}
  ],
  "uncited_claims": [],
  "recommended_action": "propose_fix",
  "escalation_reason": null
}}

MANDATORY RULES:
1. Every hypothesis MUST include evidence_ids referencing items in the evidence list. Any hypothesis without evidence will be rejected as a guess.
2. Categories must be one of: "code", "config", "resource", "cross_service", "dependency", "unknown".
3. Confidence must be a float between 0.0 and 1.0.
4. Output valid JSON ONLY. No markdown outside the JSON block. No commentary.
""".strip()


def parse_structured_diagnosis(text: str) -> Tuple[StructuredDiagnosis, bool]:
    """Parse, repair, and validate an agent response into a StructuredDiagnosis instance.

    Returns:
        (StructuredDiagnosis, was_repaired)
    Raises:
        ValueError if the response cannot be parsed or converted into valid JSON.
    """
    raw_dict, was_repaired = extract_and_parse_json(text)
    diagnosis = validate_and_build_diagnosis(raw_dict)
    return diagnosis, was_repaired
