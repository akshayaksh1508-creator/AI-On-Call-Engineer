# NightShift — Final Pitch Deck (Locked Numbers from `results/final.json`)

> **Two-Person Cross-Check Status:** Locked against `results/final.json` (Tag: `final-bench-v1.0`).

---

## Slide 1: Title & One-Sentence Value Prop
- **NightShift:** Autonomous AI On-Call Site Reliability Engineer
- *Diagnoses, sandbox-verifies, and safely resolves production incidents in **7.03s median** (vs. **560.0s** human median) at **$0.0159 per incident**.*

## Slide 2: The Problem
- On-call engineers spend **574.5s mean / 560.0s median (~9.6 min)** manually resolving even self-contained deploy and config bugs using logs, dashboards, and git (`results/human_baseline.json`).
- Existing AI alert tools summarize logs; humans still write, test, deploy, and verify every fix at 3 AM.

## Slide 3: How NightShift Works (Closed-Loop Architecture)
- **Detect** (`DetectorTrigger` < 60s SLA) $\rightarrow$ **Investigate** (Parallel tools + SQLite Memory) $\rightarrow$ **Propose PR** $\rightarrow$ **Safety Gate (`T0–T3`)** $\rightarrow$ **3-Stage Verification** (Isolated Worktree + Canary + 60s Auto-Rollback) $\rightarrow$ **6-Part Postmortem**.

## Slide 4: Safety & Trust Ladder (Zero Unsafe Actions)
- **0.0% Unsafe Actions** across all **20** final benchmark runs (`0/20`, `results/final.json`).
- **Ablation Proof:** Removing verification (`--no-verify`) increases unsafe actions from **0.0% to 40.0%** (`results/ablations/ablation_summary.json`).
- **3 Hard Guardrails:** `T3` human approval gate, automatic 60s post-promotion rollback, and global kill switch.

## Slide 5: Final Locked Benchmark Results (`results/final.json`, N = 20)
- **Total Incidents Evaluated:** **20** (15 training + 5 held-out)
- **RCA Top-1 Accuracy:** **100.0%** (`20/20`)
- **RCA Top-3 Accuracy:** **100.0%** (`20/20`)
- **Autonomous Fix Success Rate:** **80.0%** (`16/20`)
- **Held-Out Generalization (N = 5):** **100.0%** Top-3 RCA (`5/5`), **80.0%** Fix Rate (`4/5`)
- **Unseen Curveball Set (N = 5):** **5/5** resolved end-to-end (`results/curveball_results.json`)
- **Reliability (10x Consecutive Demo):** **10/10** passed (`results/reliability_10x.json`)
- **Median Resolution Time:** **7.03s** (vs. **560.0s** human median; **6.91s** mean)
- **Mean API Cost:** **$0.0159** per incident (**$0.3180** total across 20 runs; `1,590` mean tokens)

## Slide 6: Failure Analysis (4 Real Failures out of 20)
Every failed run was re-run once (`0` flaky; all `4` confirmed `real` in `results/final_failure_table.md`):
1. **`fault_008_broken_serialization` (`verify`):** Missing sandbox reproduction harness for serialization fault $\rightarrow$ *Fix:* Add catalog buggy/patched fixture.
2. **`fault_013_conn_pool_exhaustion` (`RCA` / `verify`):** Missing DB pool saturation telemetry trigger $\rightarrow$ *Fix:* Add pool-wait Prometheus metric.
3. **`fault_014_memory_leak` (`RCA` / `verify`):** Missing heap RSS growth reproducer $\rightarrow$ *Fix:* Add memory pressure fixture.
4. **`fault_016_slow_query_missing_index` (`fix`, Held-Out):** Correctly diagnosed as missing `customer_id` index, but **safely escalated (`T3`)** because DB schema migrations require human approval.

## Slide 7: Live Demo & Offline Fallback
- **Live 1080p Console (`http://127.0.0.1:8050`):** Timeline, fault/fix metric markers, collapsible tool calls, clickable evidence IDs, and 5-chart `/results` view.
- **Zero-Risk Fallback:** Offline replay (`bench/offline_replay.py`) + 720p backup video (`results/demo_backup_video.gif`).

## Slide 8: Business Case & Unit Economics
- **Target Customer:** Series B+ SaaS engineering teams (25–300 engineers).
- **Pricing:** `$1,500/mo` platform + `$2.00/verified fix` (**>99% inference margin** over `$0.0159` measured cost).
- **Market (`[ASSUMPTION]`):** ~\$3.75B TAM / ~\$600M SAM / \$6.0M 3-year SOM.

## Slide 9: Close
- **NightShift:** Autonomous incident resolution you can **verify**, **audit**, and **trust**.
