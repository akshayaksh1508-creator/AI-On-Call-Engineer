# AI On-Call Engineer: Architecture and 12-Day Execution Plan

**Team of 2** · **Working name:** NightShift · **Goal:** win on Works Live, Evidence, Ambition, Company Potential

---

## 1. Mission and Scope

**Mission:** An automated system that watches a running multi-service app, finds the root cause of a failure with cited evidence, ships a fix (patch, rollback or config change), and proves the fix worked by measured recovery.

**Scope decision (important):** Do not build a platform. Build one narrow, deep loop:
> Bad deploys, bad config and resource exhaustion in a multi-service web app, including failures where the symptom is in one service and the cause is in another.

A narrow target done well, with numbers, beats a broad platform with a single demo.

---

## 2. What Judges Want and What We Show

| Judge criterion | What they want to see | Our proof artifact |
| :--- | :--- | :--- |
| **Works, live, on a real problem** | A real running app breaks in front of them and the agent fixes it | Live demo on a 3+ service app with a real git repo, CI tests and deploy pipeline. Judge picks or injects a fault (curveball) |
| **Evidence** | Measured results, not one lucky run | Benchmark of 20+ incidents: RCA accuracy, fix success, MTTR vs human, cost, false positives, unsafe fixes, ablations, error analysis |
| **Ambition** | The hard part | Cross-service root cause, verified recovery (not just green tests), safe autonomy with auto-rollback, memory from past incidents |
| **Company potential** | Clear customer, pain, growth path | One-page business case: target customer, pricing, trust ladder (read-only to auto-fix), data moat, cost per incident vs engineer cost |

### What goes beyond judge expectations (our differentiators):
1. A benchmark instead of a demo.
2. Honest failure analysis (a 75% result with error analysis beats a claimed 100%).
3. Metric recovery graph as proof (error rate drops after the fix, shown on screen).
4. Safety built in: risk tiers, confidence thresholds, auto-rollback, kill switch.
5. Cross-service root cause incidents in the benchmark.
6. Memory: the second occurrence of a failure is solved faster (measured).
7. Cost and time per incident, compared with a human baseline we measured ourselves.
8. Live curveball: a judge chooses the fault.

---

## 3. System Architecture

```text
+-------------------- TARGET SYSTEM (Docker Compose) --------------------+
| gateway --> orders --> payments --> inventory (+ Postgres)           |
| git repo + CI tests + deploy script + feature/config flags             |
+-----------+---------------------------+-------------------------------+
            | logs (JSON), metrics       | change events (deploys, config)
            v                           v
+------------------------ PLATFORM API (FastAPI) -----------------------+
| /logs/query /metrics/query /changes /traces /service-map               |
| /repo/log /repo/diff /repo/show /deploy /rollback /config             |
+-----------+---------------------------------------------+-------------+
            |                                             ^
            v                                             |
+----------------+       +-------------------+       +------------------+
|    DETECTOR    | --->  |    INVESTIGATOR   | --->  |      FIXER       |
| thresholds,    |       | LLM agent + tools |       | patch / rollback /
| anomaly, dedupe|       | ranked hypotheses |       | config proposal  |
+----------------+       +---------+---------+       +---------+--------+
                                   |                           |
                         +---------v---------+       +---------v--------+
                         |      MEMORY       |       |   SAFETY GATE    |
                         | past incidents    |       | risk tier, conf.,|
                         | retrieval         |       | approval, limits |
                         +-------------------+       +---------+--------+
                                                               |
                                                     +---------v--------+
                                                     |     VERIFIER     |
                                                     | sandbox tests,   |
                                                     | repro, canary,   |
                                                     | metric recovery, |
                                                     | auto-rollback    |
                                                     +---------+--------+
                                                               |
                                                     +---------v--------+
                                                     |     REPORTER     |
                                                     | PR, Slack, post- |
                                                     | mortem, dashboard|
                                                     +------------------+

BENCH HARNESS + FAULT INJECTOR: injects fault -> runs full loop -> records
timings, cost, verdict -> writes results.json -> graphs
```

### Component responsibilities

| Component | Job | Key rule |
| :--- | :--- | :--- |
| **Target system** | Real app that can break and be fixed | 3 to 4 services, own repo, real tests, real deploy script |
| **Fault injector** | Inject known faults (code, config, infra) with a known ground-truth cause | Every fault has a YAML file with root cause, culprit change and expected fix |
| **Telemetry** | Structured JSON logs, request metrics (rate, errors, latency), change events | Every log line has service, trace id, timestamp |
| **Platform API** | One clean interface to all data and actions | The agent never touches Docker or git directly, only this API |
| **Detector** | Turn raw signals into an Incident object | Dedupe, group by service, record start time |
| **Investigator** | LLM agent with tools, forms and tests hypotheses | Must cite evidence IDs for every claim; output ranked top 3 with confidence |
| **Fixer** | Produce patch, rollback or config change | Smallest possible change; must include expected metric effect |
| **Safety gate** | Decide auto-apply vs human approval | See section 6 |
| **Verifier** | Prove the fix worked | Tests pass AND failing request reproduced then fixed AND canary healthy AND production metric recovered |
| **Memory** | Store solved incidents, retrieve similar ones | Retrieval result must be shown in the agent trace |
| **Reporter** | PR text, Slack message, postmortem, live dashboard | Timeline, cause, evidence, fix, confidence, cost |
| **Bench harness** | Run N incidents unattended and score them | Same code path as the live demo (no special demo mode) |

### Tech stack (keep it boring and fast)
- **Python 3.11, FastAPI, pydantic** for contracts
- **Docker Compose** for the target system (no Kubernetes)
- **Prometheus** for metrics; logs as JSON lines indexed in SQLite or Loki (choose the simpler one on Day 1)
- **Git** (local repo plus GitHub for the PR step)
- **Claude API** (a Sonnet-class model) with tool use; log token usage on every call
- **SQLite** for incidents and memory; simple embeddings or keyword plus category retrieval is enough
- **Slack webhook** for notifications
- **Streamlit** or a small HTML page for the live dashboard

---

## 4. Shared Contracts (written on Day 1, frozen on Day 6)

These JSON schemas live in `/contracts` and are the only thing both people must agree on. Everything else is independent.

- **Incident:** `id, service, started_at, symptoms[], alerts[], recent_changes[]`
- **Evidence:** `id, type (log|metric|commit|config|past_incident), ref, excerpt, ts`
- **Hypothesis:** `cause, category, confidence, evidence_ids[], culprit_change`
- **FixProposal:** `type (patch|rollback|config), diff, risk_tier, rationale, expected_metric_effect`
- **VerificationResult:** `tests_passed, repro_fixed, canary_healthy, metric_before, metric_after, recovered_at, verdict`
- **RunRecord (benchmark):** `incident_id, fault_id, t_detect, t_rca, t_fix, t_verified, rca_correct_top1, rca_correct_top3, fix_ok, unsafe, tokens, cost_usd`

**Platform API tool list (what the agent can call):** `query_logs`, `query_metrics`, `list_changes`, `git_log`, `git_diff`, `read_file`, `service_map`, `search_past_incidents`, `propose_fix`.

**Fixture rule:** Person A ships recorded incident bundles (logs, metrics, changes, repo snapshot) with a `FixtureClient` that has the same interface as the live Platform API. Person B builds and tests the agent against fixtures from Day 2, so B is never blocked waiting for A.

---

## 5. Team Split and Conflict Prevention

**Person A: Systems and Proof (owns everything that runs or measures)**
Target app, infra, telemetry, fault injector, detector, Platform API, deployer and rollback, verifier, benchmark harness, results graphs.

**Person B: Brain and Trust (owns everything that reasons or communicates)**
Investigator agent, tools wrappers and prompts, fixer, memory, safety gate, reporter, dashboard, business case, pitch deck and demo script.

### Directory ownership (no overlapping edits)

```text
/contracts         shared: changed only via PR approved by both
/target-app        A
/infra             A
/faults            A
/detector          A
/platform_api      A
/deployer          A
/verifier          A
/bench             A
/agent             B
/fixer             B
/memory            B
/safety            B
/reporter          B
/dashboard         B
/pitch             B
/tests/<component> owned by the component owner
```

### Git and collaboration rules
1. `main` is always runnable. Merge only through PR; the other person reviews (10-minute review limit).
2. Branch naming: `a/<feature>` and `b/<feature>`. Never commit to the other person's directory.
3. A change to `/contracts` needs a PR approved by both and a message in the shared chat before merging.
4. Use `CODEOWNERS` to enforce directory ownership.
5. Secrets only in `.env` (git-ignored); commit `.env.example`.
6. 15-minute sync every morning (what shipped, what is blocked, what changes in contracts) and 10 minutes at night (merge state, tomorrow's first task).
7. Integration points are tested with the fixture client first, then live.
8. No new features after Day 10. Day 11 and Day 12 are for freezing, measuring and rehearsing.

---

## 6. Safety Rules (this wins Ambition and Company Potential)

| Tier | Action | Policy |
| :--- | :--- | :--- |
| **T0** | Read logs, metrics, code, history | Always automatic |
| **T1** | Roll back the most recent deploy or revert a config change | Automatic if confidence is 0.8 or higher and canary verifies |
| **T2** | Code patch | PR plus sandbox tests plus canary; auto-merge only in demo environment at confidence 0.85 or higher |
| **T3** | Data, migrations, secrets, deleting infra | Always human approval; the agent only proposes |

**Always-on guardrails:** blast radius limited to the target namespace; one action per incident per 10 minutes; automatic rollback if error rate is worse after a fix; global kill switch; every action logged with evidence; the agent cannot disable its own guardrails.

---

## 7. Agent Design Rules

1. **Loop:** observe, hypothesize, call a tool to test, update, stop when confidence is sufficient or the step budget (about 15 tool calls) is exhausted.
2. Always check **recent changes** first (deploys and config in the 30 minutes before the incident start).
3. Always follow the **service map upstream** before blaming the service showing symptoms.
4. Every claim cites an **Evidence ID**. No evidence means the claim is marked as a guess.
5. Output a ranked top-3 hypothesis list with confidence; the confidence is calibrated against benchmark results (Day 8).
6. If confidence is low, escalate to a human with the investigation summary rather than guessing a fix.
7. Fixes must be minimal and must include a test that fails before and passes after.
8. Log tokens, tool calls and wall time for every incident.

---

## 8. Benchmark Design (the Evidence engine)

Target: 20 incidents minimum, 25 if time allows. Each has a fault file with the ground-truth cause.

| # | Category | Examples | Count |
| :--- | :--- | :--- | :--- |
| **1 to 8** | Code bug in a deploy | null pointer, off-by-one, wrong status code, bad parsing, unhandled exception, wrong timeout value, bad SQL query, broken serialization | 8 |
| **9 to 12** | Config and environment | wrong env var, expired token, wrong pool size, bad feature flag | 4 |
| **13 to 16** | Resource and infra | connection pool exhaustion, memory leak, disk full, slow query from missing index | 4 |
| **17 to 20** | Cross-service (hard) | symptom in gateway, cause in payments deploy; retry storm; upstream schema change; dependency timeout | 4 |
| **21 to 25** | Stretch | replay of public postmortems, a repeated incident to test memory | 0 to 5 |

### Metrics to report:

| Metric | Definition |
| :--- | :--- |
| **RCA accuracy** | Top-1 and top-3 match against ground truth |
| **Fix success rate** | Tests pass AND production metric recovered |
| **Time to detect, RCA, fix, verified** | Seconds from fault injection |
| **MTTR vs human** | Agent total time vs human baseline (we time ourselves manually fixing 5 incidents without the agent) |
| **Unsafe action rate** | Actions that violated policy or made things worse (target 0) |
| **False positive rate** | Incidents opened with no real fault |
| **Cost per incident** | Tokens times price |
| **Memory benefit** | Time and steps on a repeated incident with and without memory |

**Ablations (at least two):** with and without memory; with and without code access; with and without verification step.

**Honesty rule:** Report all runs. Include a failure table (which incident, why it failed, what we would change).

---

## 9. Rules for the Whole Project

### Engineering rules
1. Demo path equals benchmark path. No special-case code for the demo.
2. Every component has a test and a one-command run script.
3. Every day ends with a working `main`.
4. Log everything; the dashboard reads the same logs the agent uses.
5. Set a spend cap on the API key and cache repeated fixture calls during development.

### Demo rules
1. No pre-recorded video as the main demo (record one only as a backup).
2. Rehearse the full demo at least 10 times; track the success count.
3. Have an offline fallback (fixture replay) if the network fails.
4. The curveball: allow a judge to choose from 5 prepared fault types that are not in the order we rehearsed.

### Honesty rules
1. Never hide a failed run. Never tune the agent on the final benchmark set without disclosing it (keep 5 incidents as a held-out set).
2. State clearly what is simulated and what is real.

---

## 10. 12-Day Schedule

Format per day: A and B tasks, How to validate, Exit gate (must be true before the next day).

### Day 1: Foundation (Person A only)
Person B does no repo changes today, to avoid conflicts. B prep tasks (outside the repo): get Claude API key and set a spend cap, create the Slack workspace and webhook, create the GitHub org or repo access, write the list of 25 fault ideas in a document, research 3 real public postmortems, outline the business case.

**A (base build):**
- Create the monorepo with the directory structure above, `CODEOWNERS`, `.env.example`, `README`, `Makefile` (`make up`, `make test`, `make demo`).
- Build the target app: 3 services (gateway, orders, payments) with Postgres, each with a health endpoint, JSON logging and Prometheus metrics, plus a traffic generator that sends steady requests.
- Put the app code in its own git repo (`/target-app`) with unit tests and a deploy script.
- Write the contracts (pydantic models and JSON schemas) and a stub Platform API with the tool list returning fixture data.
- Implement one fault toggle (for example a bad deploy that causes 500 errors) and prove it by hand.
- Ship one fixture bundle and the `FixtureClient`.

**How to validate:**
- `make up` starts everything from a clean machine in under 5 minutes.
- The traffic generator shows about 0% errors on the metrics endpoint.
- Toggling the fault makes the error rate go above 20% within 30 seconds; reverting restores it.
- `make test` passes. Stub API responses validate against the contracts.

**Exit gate:** B can clone, run `make up` and call the stub API on Day 2 morning.

---

### Day 2: Eyes and Brain Skeleton
- **A:** Detector (error-rate and latency thresholds, dedupe, incident creation); real `/logs/query`, `/metrics/query`, `/changes` endpoints; fault injector framework with 5 faults (YAML ground truth).
- **B:** Agent skeleton: LLM client with tool-use loop, tool wrappers calling the Platform API (or `FixtureClient`), structured Hypothesis output, token and cost logging.

**How to validate:**
- **A:** inject each of the 5 faults; the detector opens exactly one incident each within 60 seconds; zero incidents during 10 minutes of healthy traffic (false-positive check).
- **B:** on the fixture bundle the agent returns a valid Hypothesis JSON that passes schema validation; every claim has an evidence ID.

**Exit gate:** end of day, the agent can read a real incident from the live API (even if the answer is poor).

---

### Day 3: Root Cause Reasoning
- **A:** Deploy and rollback executor (`/deploy`, `/rollback`, change events emitted on each deploy); repo endpoints (`git_log`, `git_diff`, `read_file`); grow to 10 faults including 2 cross-service.
- **B:** Root-cause prompts and strategy (recent changes first, then service map upstream); a small RCA evaluator script comparing agent output to the fault YAML.

**How to validate:**
- **A:** deploy then rollback changes the running version and emits events; the diff endpoint returns the culprit commit.
- **B:** run the RCA evaluator across the 10 faults; record top-1 and top-3 accuracy as the baseline number (expect 40 to 60%); save the results file.

**Exit gate:** a baseline RCA accuracy number exists in a file.

---

### Day 4: Fix Generation and Sandbox Verification
- **A:** Verifier part 1: apply a patch in an isolated git worktree, run the unit tests, and run a reproduction script (replays the failing request).
- **B:** Fixer: generate a minimal patch or rollback or config proposal plus a regression test; create a PR through the GitHub API; `FixProposal` schema output.

**How to validate:**
- **A:** given a known good patch and a known bad patch, the verifier returns pass and fail correctly (4 test cases).
- **B:** for the 5 simplest code faults, the fixer produces a patch that passes the sandbox; count the fix rate; PR opens with evidence in its description.

**Exit gate:** at least 3 of 5 simple faults get a sandbox-verified patch.

---

### Day 5: Canary, Recovery Proof and Safety
- **A:** Verifier part 2: deploy to a canary service instance, send traffic, compare error and latency with baseline, confirm recovery on production metrics, automatic rollback if worse.
- **B:** Safety gate (risk tiers, confidence thresholds, rate limits, kill switch) and the human-approval path (Slack message with approve and reject, or a CLI prompt).

**How to validate:**
- **A:** deliberately submit a fix that makes things worse; the system rolls back automatically within 60 seconds and logs it.
- **B:** unit tests for each tier (T3 action never auto-executes; low confidence escalates; kill switch stops all actions). 10 of 10 policy tests pass.

**Exit gate:** the verifier outputs a `VerificationResult` including before and after error-rate numbers.

---

### Day 6: End-to-End Integration (both, pair day)
- **A and B together:** wire Detector, Investigator, Fixer, Safety, Verifier, Reporter-stub into one command: `make demo FAULT=<id>`. Freeze contracts (version 1.0). Fix integration bugs together.

**How to validate:**
- Run the full loop on 3 different faults; each ends with a `VerificationResult` verdict and a PR link.
- Time each stage and write the timeline in logs.

**Exit gate (Milestone M1):** one fault goes from injection to verified recovery with no human intervention. Record a backup video of it.

---

### Day 7: Benchmark Harness and Memory
- **A:** Benchmark harness: loops over all faults, resets the environment between runs, records RunRecords to `results.json`, computes metrics and graphs. Complete faults to 20.
- **B:** Memory: store solved incidents (cause, evidence summary, fix) and retrieve similar ones; show retrieval in the agent trace; Slack reporter and postmortem generator.

**How to validate:**
- **A:** harness runs 20 incidents unattended without a crash; environment resets cleanly (healthy metrics before each run).
- **B:** a repeated incident retrieves the earlier one and uses fewer tool calls; postmortem contains timeline, cause, evidence, fix, confidence.

**Exit gate:** a full benchmark run completes and produces a results file.

---

### Day 8: Measure, Analyze, Fix Failures
- **A:** Run Benchmark v1; classify failures. Fix infrastructure-class failures (flaky resets, slow canary, detector misses). Add the cross-service faults to the harness fully.
- **B:** Fix reasoning-class failures (prompts, tool outputs, missing evidence). Calibrate confidence: check that 0.8 confidence is actually right about 80% of the time and adjust thresholds.

**How to validate:**
- Compare Benchmark v1 against v2 on the same incidents; write down every failure with a one-line cause.
- Hold out 5 incidents that neither person tunes against.

**Exit gate:** RCA top-3 at least 70% and fix success at least 55% on the training set (adjust target honestly if needed); held-out set untouched.

---

### Day 9: Ablations, Human Baseline, Live Dashboard
- **A:** Run ablations (no memory, no code access, no verification); time ourselves fixing 5 incidents manually to get the human baseline MTTR; produce charts.
- **B:** Live dashboard: incident timeline, agent trace, evidence, metric graph with fault and fix markers, verdict and cost.

**How to validate:**
- **A:** ablation table shows each removed part changes a metric (if it does not, state that honestly).
- **B:** dashboard updates in real time during a live run; a non-team member can follow the story without explanation.

**Exit gate:** a results page with 5 charts and the dashboard working live.

---

### Day 10: Hardening and the Curveball
- **A:** Reliability: run the demo scenario 10 times in a row and count successes; reduce time per stage; add 5 curveball faults not used in tuning; one-command reset.
- **B:** Business case and pitch: customer, pain, pricing, trust ladder, moat, cost per incident vs engineer cost; first draft of deck and 3-minute demo script. Feature freeze at end of day.

**How to validate:**
- **A:** at least 9 of 10 demo runs succeed; every failure has a known cause.
- **B:** someone outside the team reads the pitch and can state the customer and the value in one sentence.

**Exit gate:** feature freeze. After this, only bug fixes.

---

### Day 11: Final Measurement and Rehearsal
- **A:** Final frozen benchmark run on all incidents (including the held-out set); export final `results.json`, charts and failure table. Prepare offline fixture-replay fallback.
- **B:** Final deck with real numbers; failure analysis slide; demo script with timings; Q&A preparation (safety, hallucination, cost, scaling, competitors).

**How to validate:**
- Numbers on slides match `results.json` exactly (cross-check each one).
- Full dry run in front of one outsider with a timer; collect 3 critique points.

**Exit gate:** final numbers locked; deck complete.

---

### Day 12: Buffer, Rehearsal and Submission
- **Both:** No new features. Fix only critical bugs. Rehearse 3 full run-throughs including a curveball and a simulated failure (network down, so switch to fallback). Final checks: clean-machine setup, API key and spend cap, backup video, repo README, submission materials.

**How to validate:**
- Checklist (section 12) fully ticked.
- Two consecutive clean live runs on the demo machine.

---

## 11. Winning Strategy

1. **Lead with proof.** Open the demo with the number: *"20 incidents, X% root cause, Y% verified recovery, Z minutes faster than a human."*
2. **Demo story (3 minutes):**
   - Healthy system (20s)
   - Bad deploy and alert (30s)
   - Agent reasoning trace with cited evidence (60s)
   - PR plus canary plus recovery graph (40s)
   - Benchmark slide (20s)
   - Business line (10s)
3. **Let a judge break it.** Offer the curveball and handle a surprise fault live; this is the strongest evidence it is not rigged.
4. **Show a failure on purpose.** Present one failed incident and what the system did safely (escalated, or rolled back). This proves safe autonomy.
5. **Answer the silent question:** *"Would I let this touch production?"* Show the risk tiers and the rollback.
6. **Business slide:** customer is a team of 10 to 200 engineers with on-call but no SRE team; today's cost is 45 minutes of an engineer at 3 AM; ours is about 2 minutes and cents; trust ladder from read-only investigator to auto-fix for low-risk classes; every incident improves the customer's own memory (moat).

**Likely judge questions to prepare:**
- What if the agent is wrong?
- What stops it from deleting data?
- How does this work on a real stack (Kubernetes, Datadog)?
- How is this different from PagerDuty or Datadog AI features?
- What is the cost per incident at scale?
- How did you avoid tuning to the test set?

---

## 12. Final Checklist

- [ ] Live demo works on a clean machine with one command
- [ ] Benchmark of 20 or more incidents with `results.json` and charts
- [ ] Held-out set reported separately
- [ ] Human baseline MTTR measured
- [ ] At least 2 ablations
- [ ] Failure analysis table
- [ ] Safety tiers, auto-rollback and kill switch demonstrated
- [ ] Cross-service incident demonstrated
- [ ] Memory benefit measured
- [ ] Cost per incident computed
- [ ] Curveball prepared and rehearsed
- [ ] Backup video and offline fallback ready
- [ ] Business case slide and Q&A prepared
- [ ] Every slide number matches `results.json`

---

## 13. Risks and Fallbacks

| Risk | Fallback |
| :--- | :--- |
| **Day 1 base takes longer than planned** | Cut to 2 services and 3 faults; B starts Day 2 using fixtures regardless |
| **LLM output is unreliable or slow** | Constrain with schemas, lower step budget, cache fixture calls, retry once |
| **Verifier flaky** | Run canary checks with a fixed traffic volume and a time window; report flaky runs honestly |
| **Network fails at demo** | Offline fixture replay with live dashboard |
| **Integration slips past Day 6** | Cut memory and stretch faults first; never cut verification or the benchmark |
| **Merge conflicts** | Directory ownership plus `/contracts` PR rule; never edit the other person's folder |

### Priority if time runs short (never cut in this order, cut from the bottom):
1. Live loop on one real app
2. Verification with measured recovery
3. Benchmark with 10 or more incidents
4. Safety guardrails
5. Cross-service incidents
6. Memory
7. Dashboard polish and stretch faults

---

## 14. Detailed Daily Task Breakdown (both people, every day)

Every day has tasks for both Person A and Person B, each with what to do and how to test it. Task IDs (A1, B1 and so on) are used in standups and commit messages. Add one new folder to the ownership list: `/orchestrator` is owned by B and is created on Day 6 (A calls it, A never edits it).

**Daily routine:** 15-minute morning sync (shipped, blocked, contract changes); work in own folders; open PRs by 6 pm; cross-review within 10 minutes; 10-minute night sync to confirm main runs (`make up && make test`) and agree tomorrow's first task.

---

### Day 1: Base build (A) and Brain preparation (B)
**Goal:** A lands a runnable base with contracts and fixtures. B prepares everything the brain needs without touching A's folders; B works on branch `b/prep` in a scratch folder and merges into `/agent` and `/pitch` on Day 2 after A's skeleton is on `main`.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Create the monorepo layout from section 5, `CODEOWNERS`, `Makefile` (`up`, `test`, `demo`, `reset`), `.env.example`, linter and a CI job that runs tests | Fresh clone then `make up && make test` passes; a test PR editing a B folder is flagged by `CODEOWNERS` |
| **A2** | A | Build target app: gateway, orders, payments plus Postgres in Docker Compose. Each service has `/health`, JSON logs (service, trace_id, timestamp, level) and Prometheus `/metrics` (requests, errors, latency) | `curl /health` returns 200 on all three; one request shows the same trace_id in all three services' logs; counters rise on `/metrics` |
| **A3** | A | Traffic generator (about 10 requests per second) and the app's own git repo with 10 or more unit tests and a `deploy.sh <ref>` script that sets a version label | 10 minutes of traffic gives error rate under 1%; unit tests pass; `deploy.sh` changes the version shown on `/health` |
| **A4** | A | Contracts (pydantic models plus exported JSON schemas), stub Platform API with the 9 tools, one recorded fixture bundle and the `FixtureClient` | Fixture validates against all schemas; one contract test passes against both the stub API and `FixtureClient`; B can import the package |
| **A5** | A | First fault: a bad deploy that returns 500 errors from orders | Error rate rises above 20% within 30 s of deploy; reverting brings it under 1% within 30 s |
| **B1** | B | Claude API key with a spend cap, tiny client script that logs tokens and cost per call (in the scratch folder) | One call returns; the logged cost matches the console usage page within 5% |
| **B2** | B | Write the fault catalogue (25 faults): id, category, culprit change, visible symptom, expected fix, difficulty, in `docs/faults.md` | A reviews it: every fault has one unambiguous ground-truth cause; mix is 8 code, 4 config, 4 resource, 4 cross-service, 5 stretch |
| **B3** | B | Draft agent system prompt v0 (rules from section 7) and the JSON tool descriptions matching A's tool list | Paste one hand-made log excerpt into a chat; the output has ranked hypotheses with evidence citations and no uncited claims |
| **B4** | B | Set up integrations: Slack webhook, GitHub sandbox repo and token for test PRs; pick 3 public postmortems for stretch replays; list 5 competitors | Webhook posts a test message; a script opens and closes a test PR on the sandbox repo |

**End-of-day gate:** `main` has the runnable base; B has a prompt, a fault catalogue, working Slack and GitHub access.

---

### Day 2: Live data (A) and agent loop (B)
**Goal:** A makes incidents and data queryable live. B builds the agent loop on fixtures so nobody is blocked.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Detector: poll Prometheus every 10 s; open an incident when error rate is above 5% for 30 s or p95 latency is above 3 times baseline; dedupe by service and window; emit Incident JSON | Inject 5 faults: exactly one incident each within 60 s; 10 minutes of healthy traffic gives zero incidents; repeating one fault three times does not create duplicates |
| **A2** | A | Real endpoints `/logs/query` (service, level, time range, text), `/metrics/query`, `/changes` | Contract tests pass; log counts match a direct grep of the log file; responses under 500 ms |
| **A3** | A | Fault injector framework: `apply()`, `revert()`, ground-truth YAML; implement faults 1 to 5 (code bugs) | `apply` then `revert` three times: metrics return to baseline (errors under 1%) every time |
| **A4** | A | Record three fixture bundles from live faults (logs, metrics, changes, repo snapshot) | Bundles load in `FixtureClient`; querying a bundle returns the same answers as the live system had |
| **B1** | B | Merge scratch work into `/agent`; build the tool-use loop with step budget 15, per-call timeout and retry | Mock-LLM unit tests: loop stops at budget; handles a tool error; handles malformed JSON with one repair retry |
| **B2** | B | Tool wrappers for the 9 tools against a `PlatformClient` interface (live and fixture implementations) | Each wrapper tested against `FixtureClient`; long outputs are truncated to a token limit; errors return a structured message |
| **B3** | B | Structured output: Hypothesis and Evidence objects with generated evidence IDs and schema validation | 20 sample runs: 100% schema-valid after at most one repair; any claim without an evidence ID is flagged |
| **B4** | B | Run logger that writes the partial `RunRecord` (tokens, cost, tool calls, wall time) | Logged totals match API usage within 2% |

**End-of-day gate:** the agent reads a real incident from the live API and returns a valid Hypothesis (quality can still be poor).

---

### Day 3: Root-cause reasoning (B) and deploy plumbing (A)
**Goal:** first measured RCA accuracy; deploys and rollbacks work and are visible as change events.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Deployer: `/deploy(ref)` and `/rollback`; each emits a change event (service, from, to, time, author) | Deploy of a bad ref changes the version within 60 s; rollback restores it; events appear in `/changes` in order |
| **A2** | A | Repo endpoints `git_log`, `git_diff`, `read_file` with a path allowlist (target-app only) | A `../` path attempt is rejected; diff of the culprit commit is returned; large files are truncated |
| **A3** | A | Faults 6 to 10, including 2 cross-service (payments slow causes gateway timeouts; payments response change breaks orders) | For cross-service faults, metrics show the symptom in a different service than the culprit; detector fires on each |
| **A4** | A | RCA-only bench script: injects each fault, waits for incident, calls the agent, stores output | Runs all 10 faults unattended and leaves the environment healthy afterwards |
| **B1** | B | RCA strategy: check recent changes first, then follow the service map upstream, then cluster errors | On all 10 faults, the first 3 tool calls include `list_changes` |
| **B2** | B | RCA evaluator that compares top-1 and top-3 with the fault YAML and breaks results down by category | Unit-tested on synthetic outputs with known right and wrong answers |
| **B3** | B | Prompt iterations v1 to v3 with a change log | Baseline top-1 and top-3 saved to `results/rca_day3.json`; every prompt change has a recorded accuracy delta |
| **B4** | B | Cross-service reasoning: `service_map` use and a rule to test upstream services | On the 2 cross-service faults the agent names the upstream service as cause in at least 1 of 2 |

**End-of-day gate:** a baseline RCA accuracy number exists in a file (expect 40 to 60%).

---

### Day 4: Fix generation (B) and sandbox verification (A)
**Goal:** a proposed patch is applied in isolation and judged by tests plus a reproduction of the failing request.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Sandbox manager: one git worktree per incident, apply patch, run unit tests in a container with a 120 s timeout, clean up | Good patch passes, bad patch fails, non-applying patch gives a clear error; no leftover worktrees after 20 runs |
| **A2** | A | Reproduction scripts per fault that replay the failing request(s) taken from logs | Script fails on the faulty commit and passes on the fixed commit for all 10 faults |
| **A3** | A | `/verify/sandbox` endpoint returning a partial `VerificationResult` | Four cases give correct verdicts: good patch, bad patch, empty patch, patch touching a forbidden path (rejected) |
| **A4** | A | Faults 11 to 14 (config and environment: wrong env var, expired token, pool size, bad flag) | Each has ground truth YAML, is detected within 60 s and reverts cleanly |
| **B1** | B | Fixer v0: input Hypothesis, evidence and diff; output a minimal unified diff limited to allowed paths | `git apply --check` succeeds on at least 90% of generated diffs |
| **B2** | B | Regression test generation: a test that fails before the fix and passes after | Verifier confirms fail-then-pass on at least 3 of 5 simple faults |
| **B3** | B | Fix-type selection: rollback if the culprit is a recent deploy and the revert is clean; config change for config faults; patch otherwise | 10 table-driven unit tests; on the 14 faults the chosen type matches the expected type in at least 80% |
| **B4** | B | Open a PR through the GitHub API with cause, evidence IDs, expected metric effect and test results | PR appears on the sandbox repo with all four parts; running twice does not create a duplicate PR |

**End-of-day gate:** at least 3 of 5 simple faults get a patch that passes the sandbox.

---

### Day 5: Canary and recovery proof (A) and safety (B)
**Goal:** a fix is only called successful after canary health and production recovery, and unsafe actions are blocked.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Canary: run the fixed build as a second instance with 10 to 20% of traffic; compare error and latency with the control over a 60 s window | Good fix is marked healthy; bad fix is marked unhealthy; the pass rule (error rate no more than baseline plus 1%) is written down |
| **A2** | A | Production recovery check after promotion: watch until error rate is under 1% for 60 s; record `recovered_at` | `recovered_at` is within 5 s of a manual stopwatch reading in 3 runs |
| **A3** | A | Automatic rollback if metrics are worse after promotion, within 60 s | Inject a deliberately bad fix: rollback happens in 60 s or less and the log states the reason |
| **A4** | A | Single `/verify` endpoint (sandbox, canary, recovery) returning the full `VerificationResult` with before and after numbers | JSON validates against the contract; the numbers equal a direct Prometheus query |
| **B1** | B | Safety gate: tiers T0 to T3, confidence thresholds, one action per incident per 10 minutes, kill switch, path and service allowlist | 15 table-driven policy tests, all pass; a T3 action is never executed automatically |
| **B2** | B | Human approval path: Slack message with approve and reject (or CLI fallback), timeout leads to escalation | Approve executes once; reject does nothing; timeout escalates; double click is idempotent |
| **B3** | B | Escalation summary for low confidence: top-3 hypotheses, evidence links, suggested next step | 5 low-confidence cases each produce a summary a human can act on without re-investigating |
| **B4** | B | Append-only audit log of every decision (who, what, why, evidence IDs) | Every executed action has an entry; deleting or editing a line is detectable via a hash chain |

**End-of-day gate:** the verifier outputs before and after error-rate numbers for a fix.

---

### Day 6: Integration pair day (both people, Milestone M1)
**Goal:** one command runs the whole loop. Work in pairs on the seams; B creates `/orchestrator`, A only calls it.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Trigger path: detector sends the incident to the orchestrator automatically | Inject a fault with no manual command: a run starts within 60 s |
| **A2** | A | Executor wiring: approved actions go to deployer and verifier (T1 rollback direct; T2 patch goes sandbox, canary, promote) | A T1 rollback executes; a T2 patch passes all three stages in order |
| **A3** | A | Stage timestamps into the `RunRecord` (`t_detect`, `t_rca`, `t_fix`, `t_verified`) | In 3 runs the timestamps are strictly increasing and total time matches a stopwatch within 5 s |
| **A4** | A | Record a backup video of the first complete run | Video shows fault, agent trace, PR, canary, recovery graph |
| **B1** | B | Orchestrator state machine: Detected, Investigating, Proposed, Gated, Verifying, Resolved or Escalated or RolledBack | Unit tests for every transition and for failures (LLM timeout, verifier error, tool crash) |
| **B2** | B | Reporter stub: Slack message at each state change | Messages arrive in order with no duplicates across 3 runs |
| **B3** | B | Contract review with A, then tag `contracts v1.0` | Contract tests pass in CI on both sides; any later change needs both approvals |
| **B4** | B | `make demo FAULT=<id>` wrapper | Works from a clean shell on 3 different faults |

**End-of-day gate (M1):** one fault goes from injection to verified recovery with no human action.

---

### Day 7: Benchmark harness (A) and memory plus reporting (B)
**Goal:** 20 incidents run unattended; the agent remembers solved incidents.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Benchmark runner: for each fault, reset environment, confirm healthy for 30 s, inject, run orchestrator, write `RunRecord` | 20 faults run unattended with zero harness crashes; the environment is healthy between runs |
| **A2** | A | Faults 15 to 20 (resource and cross-service) | Each reproduces 3 times in a row and has verified ground truth |
| **A3** | A | Results aggregator and charts (accuracy, time, cost) | Metrics computed on synthetic RunRecords equal hand-calculated values |
| **A4** | A | Flake handling: classify infrastructure errors separately from agent failures | Kill a service mid-run: the record says `infra_error`, not `fail`, and the run is retried once |
| **B1** | B | Memory store in SQLite: category, symptom signature, cause, fix, evidence summary | Save and load round trip; duplicate incidents are merged |
| **B2** | B | `search_past_incidents` retrieval (keyword plus category, or embeddings) | A repeated incident retrieves its predecessor at rank 1; an unrelated incident returns nothing above the threshold |
| **B3** | B | Postmortem generator (timeline, cause, evidence, fix, verification, follow-ups) | 3 postmortems checked against a checklist; every claim has an evidence ID |
| **B4** | B | Final Slack and PR report including the recovery graph | Report for one run contains all six parts and links resolve |

**End-of-day gate:** a full benchmark run produces `results.json`.

---

### Day 8: Measure, find failures, fix them
**Goal:** Benchmark v1 on the 15 training faults (5 held-out faults stay untouched), then improve.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Run Benchmark v1 and store it as `results/v1.json` | Re-running gives results within 1 incident of the first run |
| **A2** | A | Failure triage sheet: each failure labelled detect, RCA, fix, verify or infrastructure, with a one-line cause | Every failed run has a label and a cause; counts per label add up to total failures |
| **A3** | A | Fix infrastructure failures: flaky resets, detector thresholds, canary window | Re-run affected faults 3 times each; flaky rate under 10% |
| **A4** | A | Add regression suite: all previously passing faults re-run after each change | Suite runs in under 30 minutes and reports any new failure |
| **B1** | B | Fix RCA and fixer failures (prompts, tool outputs, missing evidence) | Re-run failed incidents; log the delta per change; the regression suite shows no new failures |
| **B2** | B | Confidence calibration: bin results by confidence and set thresholds | Calibration table: in the 0.8 and above bin, accuracy is at least 80%, otherwise thresholds are raised |
| **B3** | B | Cross-service improvements | Cross-service top-3 accuracy is at least 50% |
| **B4** | B | Write the draft failure-analysis table | Each row names incident, cause of failure and proposed change |

**End-of-day gate:** RCA top-3 at least 70% and fix success at least 55% on the training set (if lower, report honestly and plan fixes).

---

### Day 9: Ablations, human baseline, live dashboard
**Goal:** show which parts matter and compare against a human.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Ablation flags: `--no-memory`, `--no-code`, `--no-verify`; run each on the same faults, 3 runs | Logs confirm the feature is really off; results saved per flag |
| **A2** | A | Human baseline: both people fix 5 incidents by hand using only logs, dashboards and git; time each | Timer sheet with start, end and notes; neither person sees the ground truth beforehand |
| **A3** | A | Charts: RCA by category, time agent vs human, cost, calibration, ablations | One command regenerates all charts from `results.json`; chart values match the file |
| **B1** | B | Live dashboard: incident timeline, agent trace, evidence, metric graph with fault and fix markers, verdict, cost | Events appear within 2 s; readable at 1080p on a projector |
| **B2** | B | Trace view: tool calls collapsible, evidence IDs clickable to the raw log line | Click an evidence ID and the exact log or commit opens |
| **B3** | B | Memory experiment: 5 repeated incidents with and without memory | Steps and time per run recorded; the difference is reported even if small |

**End-of-day gate:** results page with 5 charts and a working live dashboard.

---

### Day 10: Hardening, curveball, business case (feature freeze)
**Goal:** reliability and the story. No new features after today.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Reliability: run the demo scenario 10 times in a row | At least 9 of 10 succeed; every failure has a known cause |
| **A2** | A | Curveball set: 5 new faults the agent has never seen, injectable by id | Each runs end to end at least once; none appears in any tuning data |
| **A3** | A | Speed: parallel tool calls, tuned canary window within safe limits | Median total time is at least 20% lower than Day 8 with no accuracy loss |
| **A4** | A | One-command setup script for a clean machine | On another laptop, `make up` plus a demo run finishes in under 15 minutes |
| **B1** | B | Business case: customer, pain, pricing, trust ladder, moat, cost per incident from measured data (market sizes labelled as assumptions) | An outsider restates the customer and value in one sentence; every number traces to a source or to `results.json` |
| **B2** | B | Deck draft and a 3-minute demo script with timings | Timed rehearsal comes in at or under 3:00 |
| **B3** | B | Safety demo script: T3 escalation, auto-rollback, kill switch | Each safety feature is triggered live once in rehearsal |

**End-of-day gate:** feature freeze; only bug fixes from now on.

---

### Day 11: Final measurement and rehearsal
**Goal:** locked numbers and a rehearsed story.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Final frozen benchmark on all incidents including the held-out set; tag the commit | `results/final.json` plus a git tag; every failed run re-run once to label it flaky or real |
| **A2** | A | Export final charts and the failure table | Every number matches `results/final.json` |
| **A3** | A | Offline fallback: replay of recorded runs through the live dashboard | Disconnect the network: the replay still plays start to finish |
| **B1** | B | Insert final numbers in the deck | Two-person cross-check of every number against `results/final.json` |
| **B2** | B | Failure-analysis slide and Q&A bank answers (safety, hallucination, cost, scaling, competitors) | Mock Q&A: A asks 10 hard questions, B answers each in under 30 s |
| **B3** | B | Dry run in front of one outsider | Collect 3 critique points and fix them before end of day |

**End-of-day gate:** numbers locked; deck complete.

---

### Day 12: Buffer, rehearsal, submission
**Goal:** nothing new; make it reliable and ready.

| Task | Owner | What to do | How to test |
| :--- | :--- | :--- | :--- |
| **A1** | A | Freeze the environment: pin dependency versions, pre-pull images, check disk space, confirm API spend cap and key | Checklist ticked on the demo machine |
| **A2** | A | Two consecutive live runs on the demo machine plus one curveball | Both runs reach a verified recovery; the curveball ends in a fix or a safe escalation |
| **A3** | A | Backup video, README, submission package | A third person can set up from the README alone |
| **B1** | B | Three full pitch rehearsals including a forced failure that switches to the fallback | Each run is within time and the switch takes under 20 s |
| **B2** | B | Demo choreography: who types, who speaks, who handles the judge's curveball | One written run-sheet; both people can run it alone if needed |
| **B3** | B | Submission materials check against section 12 | Every checklist item ticked |

**Final rule:** no merges after the last rehearsal; if something breaks, use the fallback instead of fixing it.
