"""Agent System Prompt v0 and Reasoning Templates.

Owner: Person B (Brain & Trust)
Implements Section 7 Agent Design Rules:
1. Operating Loop: observe, hypothesize, test with tools, update, stop when confident or budget (15 calls) exhausted.
2. Check recent changes first (deploys and config in the 30 minutes before incident start).
3. Follow the service map upstream before blaming the service showing symptoms.
4. Every claim must cite an Evidence ID. Uncited claims are marked as guesses.
5. Output ranked top-3 hypotheses with calibrated confidence (0.0 to 1.0).
6. Escalate to human with investigation summary if confidence is low.
7. Fixes must be minimal and risk-tiered.
8. Log tokens, tool calls, and wall time.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from contracts.models import Evidence, Hypothesis, Incident

SYSTEM_PROMPT_V0 = """You are NightShift, an autonomous Tier-1 AI On-Call Site Reliability Engineer.
Your mandate is to rapidly diagnose production incidents, pinpoint the precise root cause with empirical proof, and propose minimal, safe remediations.

### CORE OPERATING RULES (MANDATORY):
1. **THE REASONING LOOP**:
   - **Observe**: Parse incident symptoms, alerts, and initial telemetry.
   - **Hypothesize**: Formulate competing plausible root-cause hypotheses across categories: code, config, resource, cross_service, dependency.
   - **Test with Tools**: Call platform tools to confirm or falsify each hypothesis.
   - **Update**: Adjust probabilities based on empirical findings.
   - **Stop**: Stop when confidence in a single root cause is high (>= 0.85) or when the step budget (15 tool calls) is reached.

2. **RECENT CHANGES FIRST**:
   - Always check deployments and configuration changes within the 30 minutes prior to incident start first (`list_changes`, `git_log`). Over 80% of production outages stem from recent changes.

3. **SERVICE MAP UPSTREAM RULE**:
   - When a service manifests errors (e.g. Gateway 502 or Orders 500), follow the service architecture upstream (`service_map`) before blaming the symptom service. Distinguish between the *victim service* and the *culprit service*.

4. **STRICT EVIDENCE CITATION RULE**:
   - **EVERY CLAIM MUST CITE AN EVIDENCE ID** (e.g. `[ev_log_001]`, `[ev_metric_001]`, `[ev_commit_001]`).
   - You must construct an `evidence` list containing all cited pieces of telemetry, logs, diffs, or metrics with unique IDs, reference pointers, and raw excerpts.
   - Any claim or hypothesis not grounded in an explicit Evidence ID must be explicitly flagged as a `[GUESS]`. Zero uncited claims may be presented as facts.

5. **RANKED TOP-3 HYPOTHESES**:
   - Provide up to 3 ranked hypotheses ordered from highest to lowest confidence.
   - Calibrate confidence between 0.0 and 1.0 based strictly on supporting vs contradictory evidence.

6. **SAFE REMEDIATION & ESCALATION**:
   - Propose minimal, targeted fixes: rollback if a bad deploy was identified (T1), configuration revert (T1), or precise code patch (T2).
   - If confidence is low (< 0.60) or investigation budget is exhausted without conclusive proof, DO NOT guess a blind fix: escalate immediately to a human engineer with the full investigation summary.

### OUTPUT FORMAT:
When delivering diagnostic findings, you MUST output valid JSON matching the following schema:
```json
{
  "investigation_summary": "Concise summary of investigation steps and observations.",
  "evidence": [
    {
      "id": "ev_log_001",
      "type": "log",
      "ref": "target-app/services/orders/main.py:42",
      "excerpt": "TypeError: 'NoneType' object is not subscriptable",
      "ts": "2026-11-22T21:40:02.145Z"
    }
  ],
  "hypotheses": [
    {
      "cause": "Detailed explanation of failure mechanism citing evidence IDs [ev_log_001].",
      "category": "code",
      "confidence": 0.95,
      "evidence_ids": ["ev_log_001"],
      "culprit_change": "dep_20261122_v1.0.1"
    }
  ],
  "uncited_claims": [],
  "recommended_action": "propose_fix",
  "escalation_reason": null
}
```
""".strip()


def build_investigation_user_prompt(
    incident: Optional[Incident] = None,
    log_excerpt: Optional[str] = None,
    recent_changes_summary: Optional[str] = None,
    additional_context: Optional[str] = None,
) -> str:
    """Build a standardized user prompt for an on-call diagnostic run."""
    sections = [
        "Please investigate the following production telemetry and provide your root-cause analysis according to Section 7 rules."
    ]

    if incident:
        sections.append("### INCIDENT CONTEXT:")
        sections.append(f"- Incident ID: {incident.id}")
        sections.append(f"- Impacted Service: {incident.service}")
        sections.append(f"- Started At: {incident.started_at}")
        sections.append(f"- Symptoms: {', '.join(incident.symptoms) if incident.symptoms else 'None reported'}")
        sections.append(f"- Triggered Alerts: {', '.join(incident.alerts) if incident.alerts else 'None'}")
        if incident.recent_changes:
            sections.append(f"- Recent Changes: {', '.join(incident.recent_changes)}")

    if recent_changes_summary:
        sections.append("### RECENT DEPLOYS / CONFIG CHANGES:")
        sections.append(recent_changes_summary.strip())

    if log_excerpt:
        sections.append("### LOG EXCERPT:")
        sections.append("```\n" + log_excerpt.strip() + "\n```")

    if additional_context:
        sections.append("### ADDITIONAL SYSTEM CONTEXT:")
        sections.append(additional_context.strip())

    sections.append(
        "Analyze the logs and context. Extract all relevant Evidence objects with unique IDs (e.g. ev_log_001). "
        "Formulate your top-3 ranked hypotheses citing these evidence IDs. "
        "Mark any unverified claim in uncited_claims. Return your final analysis in valid JSON."
    )

    return "\n\n".join(sections)


def extract_json_from_llm_text(text: str) -> Dict[str, Any]:
    """Robustly extract and parse a JSON dictionary from LLM response text."""
    text = text.strip()
    
    # 1. Try direct JSON parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. Try fenced markdown code block ```json ... ```
    json_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_block_match:
        try:
            data = json.loads(json_block_match.group(1))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 3. Find outermost matching curly braces
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    raise ValueError(f"Could not extract valid JSON object from LLM response:\n{text[:300]}...")


def parse_agent_response(
    response_text: str,
) -> Tuple[List[Hypothesis], List[Evidence], List[str], Dict[str, Any]]:
    """Parse and validate LLM diagnostic output against contracts.models schemas.

    Returns:
        (hypotheses, evidence_list, uncited_claims, raw_dict)
    
    Ensures:
        - Every Hypothesis passes Pydantic schema validation
        - Every Evidence passes Pydantic schema validation
        - All cited evidence IDs are present in the evidence list
        - Any hypothesis lacking evidence is marked in uncited_claims as a guess
    """
    raw_data = extract_json_from_llm_text(response_text)

    # Parse Evidence items
    raw_evidence = raw_data.get("evidence", [])
    evidence_list: List[Evidence] = []
    known_evidence_ids = set()

    for item in raw_evidence:
        ev = Evidence.model_validate(item)
        evidence_list.append(ev)
        known_evidence_ids.add(ev.id)

    # Parse Hypotheses
    raw_hypotheses = raw_data.get("hypotheses", [])
    hypotheses: List[Hypothesis] = []
    uncited_claims: List[str] = list(raw_data.get("uncited_claims", []))

    for item in raw_hypotheses:
        hyp = Hypothesis.model_validate(item)
        hypotheses.append(hyp)

        # Check evidence citations
        if not hyp.evidence_ids:
            uncited_claims.append(
                f"[GUESS] Hypothesis '{hyp.cause[:80]}' has no cited evidence IDs."
            )
        else:
            for eid in hyp.evidence_ids:
                if eid not in known_evidence_ids:
                    uncited_claims.append(
                        f"[UNREFERENCED] Hypothesis cites unknown evidence ID '{eid}'."
                    )

    # Sort hypotheses by confidence descending
    hypotheses.sort(key=lambda h: h.confidence, reverse=True)

    return hypotheses, evidence_list, uncited_claims, raw_data
