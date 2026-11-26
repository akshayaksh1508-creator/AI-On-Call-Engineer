# NightShift — Day 11 Outsider Dry-Run Critique (`B3`)

- **Date:** Day 11
- **Presenter:** Person B (with Person A operating live demo cues)
- **Outsider Reviewer:** Independent technical reviewer (first time seeing the NightShift pitch and `pitch/deck_final.md`)
- **Scope Reviewed:** `pitch/deck_final.md`, `pitch/demo_script_3min.md`, and `pitch/qa_bank.md`

---

## 3 Critique Points Collected & Fixes Applied

### Critique 1 — Slide 4 (`Benchmark Results`) lacked immediate context on the 4 failed fixes
- **Outsider Feedback:** *"Seeing 80% fix rate and 0% unsafe rate is strong, but before Slide 6 I immediately wondered why the 4 failed runs happened and whether any of them broke production."*
- **Fix Applied:**
  - Added explicit callout in `pitch/deck_final.md` (Slide 4 & Slide 6) clarifying that all 4/20 non-resolved runs failed safely inside verification/guardrails with **0.0% unsafe actions**, and cross-referenced Slide 6's failure-mode breakdown (`config-drift`, `ambiguous multi-service contention`, `read-only permission boundary`, `transient timeout`).

### Critique 2 — Demo transition into the safety guardrail felt too fast for a non-SRE
- **Outsider Feedback:** *"When you mention the policy gate blocks unsafe commands, a non-SRE judge won't immediately see why an LLM couldn't just bypass it."*
- **Fix Applied:**
  - Tightened the spoken bridge in `pitch/qa_bank.md` (`Q1`) and aligned Slide 3 (`Architecture & Safety`) in `pitch/deck_final.md` to emphasize that the policy engine is **deterministic code outside the LLM**, enforcing an explicit allowlist and blast-radius cap before any container execution.

### Critique 3 — Held-out split vs. total N=20 needed clearer visual separation
- **Outsider Feedback:** *"Make sure judges don't think you tested on only 5 scenarios or overfit to 20."*
- **Fix Applied:**
  - Highlighted both **N = 20 total scenarios** and the **5 unseen held-out scenarios (4/5 = 80.0% fix rate, 100.0% Top-3 RCA)** side by side in `pitch/deck_final.md` (Slide 4) and `pitch/qa_bank.md` (`Q8`).

---

## Verification Status
- All 3 critique points resolved before end of Day 11.
- `pitch/cross_check.py` re-verified against `results/final.json` after all deck edits.
