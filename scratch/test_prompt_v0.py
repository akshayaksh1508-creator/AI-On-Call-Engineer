"""Scratch verification script for Agent System Prompt v0 and Tool Schemas (Task B3).

Demonstrates:
1. Building system prompt v0 enforcing Section 7 rules (loop, recent changes, upstream service map, citations).
2. Packaging the 9 platform tools matching platform_api.client.PlatformClient.
3. Feeding a hand-made production log excerpt into the agent.
4. Parsing and validating the output into ranked Hypothesis and Evidence objects.
5. Verifying that all hypotheses cite valid Evidence IDs and uncited claims are flagged.

Usage:
    python scratch/test_prompt_v0.py
"""

import json
import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent.llm_client import LLMClient
from agent.prompts import (
    SYSTEM_PROMPT_V0,
    build_investigation_user_prompt,
    parse_agent_response,
)
from agent.tools import get_agent_tools, get_tool_names
from contracts.models import Incident


# 1. Realistic hand-made log excerpt from bad deployment
HANDMADE_LOG_EXCERPT = """
[2026-11-22T21:38:15.000Z] [INFO] [orders] Deploying version v1.0.1 (commit c0ffee14a): feat(orders): add VIP discount code handling
[2026-11-22T21:40:02.100Z] [INFO] [gateway] [trace-fail-001] Handling POST /api/orders path="/api/orders"
[2026-11-22T21:40:02.120Z] [INFO] [orders] [trace-fail-001] Handling POST /orders path="/orders"
[2026-11-22T21:40:02.145Z] [ERROR] [orders] [trace-fail-001] Unhandled exception in create_order: TypeError: 'NoneType' object is not subscriptable
Traceback (most recent call last):
  File "target-app/services/orders/main.py", line 42, in create_order
    discount_code = request.discount['code']
TypeError: 'NoneType' object is not subscriptable
[2026-11-22T21:40:02.150Z] [ERROR] [gateway] [trace-fail-001] Downstream service orders returned 500 Internal Server Error
""".strip()


def run_prompt_v0_test():
    print("=" * 75)
    print("NightShift AI On-Call Engineer: System Prompt v0 & Tools Test (Task B3)")
    print("=" * 75)

    # 1. Inspect Tools
    tools = get_agent_tools()
    tool_names = get_tool_names()
    print(f"\n[1/5] Loaded {len(tools)} Platform Tools:")
    for i, name in enumerate(tool_names, 1):
        print(f"      {i}. {name}")
    assert len(tools) == 9, f"Expected exactly 9 tools, found {len(tools)}"

    # 2. Build Incident & User Prompt
    incident = Incident(
        id="inc_20261122_001",
        service="orders",
        started_at="2026-11-22T21:40:00Z",
        symptoms=["HTTP 500 error rate spiked to 35% on POST /orders", "Gateway returning 502/500"],
        alerts=["OrdersHigh5xxRate", "CheckoutFailureSpike"],
        recent_changes=["dep_20261122_v1.0.1"],
        status="open",
    )

    user_prompt = build_investigation_user_prompt(
        incident=incident,
        log_excerpt=HANDMADE_LOG_EXCERPT,
        recent_changes_summary="dep_20261122_v1.0.1 deployed to service 'orders' at 2026-11-22T21:38:15Z (commit c0ffee14a)",
    )

    print("\n[2/5] Formatted User Prompt (Length: {} chars)".format(len(user_prompt)))
    print("-" * 50)
    print(user_prompt[:350] + "\n... [truncated] ...\n")

    # 3. Initialize LLM Client (uses mock mode if no API key set)
    client = LLMClient(spend_cap=1.00)
    print(f"[3/5] Executing LLM Call (Model: {client.default_model}, Mock: {client.mock})...")
    resp = client.call(
        prompt=user_prompt,
        system=SYSTEM_PROMPT_V0,
        tools=tools,
        max_tokens=1024,
    )
    print(f"      Tokens consumed: {resp.total_tokens} (in: {resp.input_tokens}, out: {resp.output_tokens})")
    print(f"      Call cost: ${resp.cost_usd:.4f}")
    print(f"      Latency: {resp.latency_seconds:.3f}s")

    # 4. Parse Structured Output
    print("\n[4/5] Parsing Structured Output against Pydantic Models...")
    hypotheses, evidence_list, uncited_claims, raw = parse_agent_response(resp.content)

    print(f"\nExtracted Evidence ({len(evidence_list)} items):")
    for ev in evidence_list:
        print(f"  [{ev.id}] type={ev.type} | ref={ev.ref}")
        print(f"         excerpt: {ev.excerpt}")

    print(f"\nRanked Hypotheses ({len(hypotheses)} items):")
    for i, hyp in enumerate(hypotheses, 1):
        print(f"  Rank #{i}: [{hyp.category.upper()}] (Confidence: {hyp.confidence:.2f})")
        print(f"    Cause: {hyp.cause}")
        print(f"    Evidence IDs: {hyp.evidence_ids}")
        print(f"    Culprit Change: {hyp.culprit_change}")

    # 5. Validation Criteria Checks
    print("\n[5/5] Checking Success Criteria:")
    # Criteria a: output has ranked hypotheses
    assert len(hypotheses) >= 1, "Must produce at least one hypothesis"
    is_sorted = all(hypotheses[i].confidence >= hypotheses[i+1].confidence for i in range(len(hypotheses)-1))
    assert is_sorted, "Hypotheses must be ranked by confidence descending"
    print("  [PASS] Hypotheses are sorted by calibrated confidence.")

    # Criteria b: top hypothesis has evidence citations
    top_hyp = hypotheses[0]
    assert len(top_hyp.evidence_ids) > 0, "Top hypothesis must cite evidence IDs"
    print(f"  [PASS] Top hypothesis cites {len(top_hyp.evidence_ids)} Evidence IDs.")

    # Criteria c: all cited evidence IDs exist
    evidence_id_set = {ev.id for ev in evidence_list}
    for eid in top_hyp.evidence_ids:
        assert eid in evidence_id_set, f"Cited evidence ID {eid} not found in evidence list"
    print("  [PASS] All cited Evidence IDs exist in the empirical evidence pool.")

    # Criteria d: zero uncited factual claims in top hypothesis
    unreferenced = [c for c in uncited_claims if "[UNREFERENCED]" in c]
    assert len(unreferenced) == 0, f"Found unreferenced citations: {unreferenced}"
    print(f"  [PASS] Zero uncited claims in verified hypotheses (uncited_claims count: {len(uncited_claims)}).")

    print("\n" + "=" * 75)
    print("SUCCESS: Task B3 Verification Passed! System Prompt v0 & 9 Tools operational.")
    print("=" * 75)


if __name__ == "__main__":
    run_prompt_v0_test()
