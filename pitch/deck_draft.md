# NightShift — Pitch Deck Draft (Day 10 Task B2)

## Slide 1: Title & Hook
- **NightShift:** Autonomous AI On-Call Site Reliability Engineer
- *From Pager Alert to Verified Recovery in 7 Seconds — at $0.015 per Incident.*

## Slide 2: The Problem
- On-call engineers spend **9.6 minutes** on average diagnosing even straightforward deploy/config regressions (`results/human_baseline.json`), and far longer in production at 3 AM.
- Existing AI alert bots only summarize logs — engineers still have to write, test, deploy, and verify fixes manually.

## Slide 3: The Solution — Closed-Loop Autonomous SRE
- **Detect** $\rightarrow$ **Investigate (Parallel Tools + Memory)** $\rightarrow$ **Propose PR** $\rightarrow$ **Safety Gate (`T0–T3`)** $\rightarrow$ **Verify (Worktree Sandbox + Canary + Auto-Rollback)** $\rightarrow$ **Postmortem**.

## Slide 4: Safety & Trust Ladder (Why Teams Can Trust It)
- **3-Stage Verification:** Reproduces the bug on baseline, passes tests in an isolated git worktree, and passes canary (`+1%` error rule).
- **60s Auto-Rollback & Global Kill Switch:** Instant recovery if post-promotion metrics degrade.
- **Ablation Proof:** Removing verification (`--no-verify`) causes unsafe actions to jump from **0% to 40%** (`results/ablations/ablation_summary.json`).

## Slide 5: Measured Results (Agent vs. Human)
- **Median Resolution Time:** **7.03s** (NightShift) vs. **560.0s** (Human SRE) — **~80x faster** (`results/speed_comparison.json`, `results/human_baseline.json`).
- **RCA Top-3 Accuracy:** **100.0%** across 15 training faults; **80.0%** autonomous fix rate (`results/v2_improved.json`).
- **Reliability & Unseen Generalization:** **10/10** consecutive demo runs passed (`results/reliability_10x.json`); **5/5** unseen curveball faults resolved (`results/curveball_results.json`).

## Slide 6: Live Demo Highlights
- 1080p Live Console (`http://127.0.0.1:8050`): Timeline, fault/fix metric markers, collapsible tool calls, clickable evidence IDs, and 5-chart results view (`/results`).

## Slide 7: Business Case & Unit Economics
- **Target Customer:** Series B+ SaaS teams (25–300 engineers).
- **Cost & Margin:** `$0.0147` measured compute cost per incident vs. `$1,500/mo + $2/fix` pricing (**>99% inference gross margin**).
- **Market (`[ASSUMPTION]`):** ~\$3.75B TAM / ~\$600M SAM / \$6.0M 3-year SOM.

## Slide 8: Close & Ask
- **NightShift:** Autonomous incident resolution you can verify, audit, and trust.
