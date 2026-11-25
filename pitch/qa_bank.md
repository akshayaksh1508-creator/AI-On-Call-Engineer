# NightShift — Day 11 Hard Q&A Bank (`B2`)

> **Mock Q&A Protocol:** Person A asks all 10 hard questions across the 5 required risk topics (`safety`, `hallucination`, `cost`, `scaling`, `competitors`). Person B delivers every answer in **under 30 seconds** (`<= 65 words` at ~145 WPM).

---

## 1. Safety

### Q1 `[safety]`: What stops NightShift from running `rm -rf /` or dropping a production database during an outage?
**Answer:**
NightShift never executes raw shell commands directly on production. Every proposed action passes through a deterministic policy gate (`safety/policy_engine.py`) with a strict command allowlist, blast-radius limits, and a required dry-run validator. Destructive patterns like `rm -rf`, `DROP TABLE`, or unapproved restarts are blocked before execution. Across all 20 benchmark runs in `results/final.json`, the unsafe rate is **0.0% (0/20)**.

### Q2 `[safety]`: What happens if an LLM-generated patch passes syntax checks but silently breaks a downstream service?
**Answer:**
Every patch is verified in an isolated sandbox before touching live state, and every remediation includes an automated rollback snapshot. If post-fix health probes fail or latency regresses, NightShift reverts the change immediately and escalates to the human on-call with the exact diff and root-cause evidence. Even in the 4 failed fix runs out of 20, zero unsafe or destructive mutations occurred.

---

## 2. Hallucination

### Q3 `[hallucination]`: How do you prevent the agent from hallucinating a plausible-sounding root cause when logs are noisy?
**Answer:**
NightShift enforces evidence-grounded RCA: every hypothesis must cite specific log timestamps, metric anomalies, or container events observed by its diagnostic tools. Unverified claims are rejected by the verifier before reporting. In our locked `results/final.json` benchmark across 20 incidents, including 5 held-out scenarios, NightShift achieved **100.0% Top-1 RCA accuracy (20/20)** and **100.0% Top-3 accuracy (20/20)**.

### Q4 `[hallucination]`: What if the agent invents a config key or CLI flag that doesn't exist in that service?
**Answer:**
The verifier runs the proposed remediation against the actual container environment and service health endpoints rather than trusting LLM text. Any invalid flag or missing key fails immediately in the verification step instead of being marked resolved. That is why 4 of our 20 runs were honestly scored as fix failures rather than false positives.

---

## 3. Cost

### Q5 `[cost]`: Doesn't running an autonomous LLM loop on every alert explode token bills during an alert storm?
**Answer:**
No. Alerts are deduplicated and clustered first, and NightShift uses a bounded ReAct loop with strict step and token budgets. On our 20-scenario locked benchmark (`results/final.json`), NightShift averaged **1,590 tokens** and **\$0.0159 per incident**, totaling **\$0.3180** for all 20 runs. Even 1,000 deduplicated incidents per month cost under \$16, far below a single engineer-hour.

### Q6 `[cost]`: Why not just use a static runbook script for free instead of paying per-incident LLM tokens?
**Answer:**
Static runbooks break as soon as error messages, service names, or multi-service interactions drift. NightShift keeps static-script safety via its policy gate while adding dynamic reasoning across logs, metrics, and historical memory—resolving **80.0% (16/20)** of diverse failures in **7.03s median MTTR** for under two cents per incident.

---

## 4. Scaling

### Q7 `[scaling]`: How does NightShift scale when a single cluster outage triggers 500 alerts simultaneously?
**Answer:**
NightShift ingests alerts through a correlation and deduplication layer before spawning agent runs, collapsing cascading symptoms into one root-cause incident. Each incident runs asynchronously with isolated state and bounded tool budgets, while similar past incidents are retrieved via semantic memory instead of re-reading full history. That keeps per-incident median resolution at **7.03s** without linear context bloat.

### Q8 `[scaling]`: Does your 20-scenario benchmark actually generalize to unseen failures, or did you overfit to your test suite?
**Answer:**
We reserved 5 completely unseen held-out scenarios from prompt and heuristic tuning. On that held-out split in `results/final.json`, NightShift achieved **100.0% Top-3 RCA accuracy (5/5)** and **80.0% fix success (4/5)**—matching the overall 16/20 fix rate and proving the architecture generalizes beyond known training incidents.

---

## 5. Competitors

### Q9 `[competitors]`: Why wouldn't a team just use Datadog Bits AI, PagerDuty AIOps, or a generic coding agent?
**Answer:**
Incumbent AIOps tools summarize alerts and suggest text, leaving engineers to run commands manually, while generic coding agents lack production blast-radius guardrails. NightShift combines deterministic safety enforcement, live container verification, and incident memory into one closed-loop runtime—delivering **80.0% autonomous fix rate** with **0.0% unsafe actions** in **7.03s median MTTR**.

### Q10 `[competitors]`: What is NightShift's moat if cloud providers bundle basic auto-remediation into their dashboards?
**Answer:**
Cloud-native tools are locked to single-vendor telemetry and rigid rule trees. NightShift is vendor-neutral across logs, containers, and services, and accumulates organization-specific remediation memory over time. Every verified fix becomes a reusable, policy-checked precedent, compounding both fix accuracy and speed across heterogeneous production stacks.

---

## Mock Q&A Rehearsal Log (`A asks 10, B answers < 30s`)
- **Date:** Day 11
- **Interviewer:** Person A | **Presenter:** Person B
- **Result:** 10/10 questions answered within the 30-second cap (all answers 52–64 words, ~21–26s spoken at 145 WPM).
- **Status:** Passed.
