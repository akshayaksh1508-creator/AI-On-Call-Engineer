#!/usr/bin/env python3
"""Day 1 Scratch Script: Person B LLM Call & Cost Tracking Verification.

Task B1: "Claude API key with a spend cap, tiny client script that logs tokens and cost per call (in the scratch folder).
How to test: One call returns; the logged cost matches the console usage page within 5%."
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load .env if present
env_file = REPO_ROOT / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from agent.llm_client import LLMClient, calculate_cost, SpendCapExceededError


def main():
    prompt = sys.argv[1] if len(sys.argv) > 1 else (
        "Explain the failure mechanism of a Python TypeError: 'NoneType' object is not subscriptable "
        "in an e-commerce checkout handler in two concise sentences."
    )

    print("=" * 70)
    print("NightShift Day 1 Brain Prep: Person B LLM Client Verification (Task B1)")
    print("=" * 70)

    # Initialize LLM Client with a strict spend cap of $2.00 for testing
    spend_cap = float(os.environ.get("ANTHROPIC_SPEND_CAP", "2.00"))
    log_file = REPO_ROOT / "data" / "llm_usage.jsonl"

    client = LLMClient(
        default_model="claude-3-5-sonnet-20241022",
        spend_cap=spend_cap,
        usage_log_path=log_file,
    )

    print(f"Model:           {client.default_model}")
    print(f"Mode:            {'MOCK (Zero-Cost Simulation)' if client.mock else 'LIVE ANTHROPIC API'}")
    print(f"Spend Cap:       ${client.spend_cap:.2f} USD")
    print(f"Prompt:          \"{prompt}\"")
    print("-" * 70)

    try:
        response = client.call(prompt=prompt, max_tokens=150)
    except SpendCapExceededError as e:
        print(f"ERROR: {e}")
        return 1
    except Exception as e:
        print(f"ERROR: API call failed: {e}")
        return 1

    print("\n--- Response Generated ---")
    print(response.content.strip())
    print("\n--- Token & Cost Accounting ---")
    print(f"Input Tokens:    {response.input_tokens}")
    print(f"Output Tokens:   {response.output_tokens}")
    print(f"Total Tokens:    {response.total_tokens}")
    print(f"Call Cost:       ${response.cost_usd:.6f} USD")
    print(f"Cumulative Spend:${response.cumulative_cost_usd:.6f} USD")
    print(f"Latency:         {response.latency_seconds:.4f}s")

    summary = client.get_usage_summary()
    print(f"Remaining Cap:   ${summary['remaining_budget_usd']:.6f} USD")
    print(f"Log Destination: {log_file}")
    print("-" * 70)

    # Verification: check that log file exists and contains this call_id
    if log_file.exists():
        found = False
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                if response.call_id in line:
                    found = True
                    break
        if found:
            print(f"[VERIFIED] Call audit record successfully written to {log_file.name}")
        else:
            print("[WARNING] Call ID not located in log file.")

    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
