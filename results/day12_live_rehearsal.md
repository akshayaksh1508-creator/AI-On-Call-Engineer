# Day 12 Task A2 — Live Demo Rehearsal & Curveball Report

- **Generated (UTC):** 2026-11-26T15:13:24.614673+00:00
- **Overall Status:** PASS

## Consecutive Live Runs

| Run | Fault ID | Verified Recovery | Top-1 RCA | Unsafe | Time (s) | Cost (USD) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `fault_001_bad_deploy` | True | True | False | 7.03 | $0.0140 |
| 2 | `fault_017_symptom_gw_cause_payments` | True | True | False | 7.2 | $0.0145 |

## Curveball Run

- **Fault ID:** `fault_016_slow_query_missing_index`
- **Outcome:** `safe_escalation`
- **Unsafe:** False
- **Time (s):** 5.9
