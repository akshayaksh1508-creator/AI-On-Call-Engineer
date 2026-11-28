# NightShift: Autonomous AI On-Call Engineer

> **Team of 2** · **Working Name:** NightShift  
> **Goal:** Win on Works Live, Evidence, Ambition, and Company Potential.

NightShift is an automated system that monitors a running multi-service application, identifies the root cause of failures with cited telemetry evidence, ships targeted fixes (patches, rollbacks, or config updates), and validates recovery through measured metric changes.

---

## Monorepo Architecture & Directory Ownership

In accordance with Section 5 of the architecture specification, responsibilities and directory ownership are strictly segregated:

| Directory | Owner | Role & Responsibility |
| :--- | :--- | :--- |
| `/contracts` | **Shared** (A & B) | Pydantic models & JSON schemas. Frozen on Day 6; changes require dual approval. |
| `/target-app` | **Person A** | 3-to-4 service target application (gateway, orders, payments, Postgres). |
| `/infra` | **Person A** | Docker Compose and Prometheus observability stack. |
| `/faults` | **Person A** | Fault injection framework and 20+ ground-truth YAML fault definitions. |
| `/detector` | **Person A** | Telemetry poller, anomaly threshold detection, deduplication, incident creation. |
| `/platform_api` | **Person A** | FastAPI interface isolating telemetry and operational actions. |
| `/deployer` | **Person A** | Deploy and rollback executor emitting structured change events. |
| `/verifier` | **Person A** | Git worktree sandbox, canary testing, and production recovery verification. |
| `/bench` | **Person A** | Benchmark harness, unattended evaluation runner, and metrics aggregator. |
| `/agent` | **Person B** | Investigator LLM agent, tool-use loop, and ranked hypothesis generation. |
| `/fixer` | **Person B** | Patch generation, rollback proposals, config updates, and regression tests. |
| `/memory` | **Person B** | SQLite storage and semantic retrieval for solved past incidents. |
| `/safety` | **Person B** | T0-T3 safety gate, confidence thresholds, rate limits, and kill switch. |
| `/reporter` | **Person B** | Slack notifications, incident postmortems, and GitHub PR formatting. |
| `/dashboard` | **Person B** | Live real-time dashboard (incident timeline, agent trace, recovery graphs). |
| `/pitch` | **Person B** | Business case, 3-minute pitch deck, demo script, and Q&A bank. |
| `/orchestrator` | **Person B** | Autonomous incident state machine (created on Day 6). |
| `/tests/<component>`| **Owner** | Unit and integration test suites owned by respective component owners. |

---

## Quickstart

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Git

### Standard Commands

You can execute commands via `make` (Linux/macOS/Git Bash), `.\make.ps1` (Windows PowerShell), or `python run.py`:

```bash
# 1. Start target app & infrastructure
make up
# or on Windows: .\make.ps1 up
# or: python run.py up

# 2. Run linters, contract tests, and unit tests
make test
# or on Windows: .\make.ps1 test
# or: python run.py test

# 3. Trigger end-to-end demo incident loop
make demo FAULT=1
# or on Windows: .\make.ps1 demo -Fault 1
# or: python run.py demo --fault 1

# 4. Clean caches, worktrees, and stop containers
make reset
# or on Windows: .\make.ps1 reset
# or: python run.py reset
```

---

## Git & Collaboration Rules

1. **`main` is always runnable.** All additions must pass linters and tests.
2. **Branch naming:** `a/<feature>` for Person A and `b/<feature>` for Person B. Never commit to the other person's directory.
3. **Contracts approval:** Any change to `/contracts` requires a PR approved by both engineers.
4. **CODEOWNERS:** Directory ownership is enforced by `.github/CODEOWNERS` and verified in CI.
5. **Secrets:** Stored only in `.env` (git-ignored); template provided in `.env.example`.
6. **Integration rule:** Person B develops against `FixtureClient` before live services are wired.

---

## Clean-Machine Setup (Third-Person Reproducible)

A third party can set up and verify NightShift from this README alone:

### 1. Clone & Create Virtual Environment
```bash
git clone https://github.com/akshayaksh1508-creator/AI-On-Call-Engineer.git
cd AI-On-Call-Engineer
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
```

### 2. Install Frozen Dependencies
```bash
pip install -r requirements-frozen.txt
```
*(Or run the one-command clean-machine setup script: `bash scripts/setup_clean_machine.sh` on Linux/macOS or `.\scripts\setup_clean_machine.ps1` on Windows.)*

### 3. Configure Environment & Spend Cap
```bash
cp .env.example .env
```
Edit `.env` to set `ANTHROPIC_API_KEY` (optional — NightShift also runs in deterministic offline/fixture mode) and confirm `ANTHROPIC_SPEND_CAP_USD=50.00`.

### 4. Verify Environment Freeze & Full Test Suite
```bash
python -m bench.env_freeze
python run.py test
```

### 5. Run Live Demo, Dashboard, & Offline Backup Video
- **Live Incident Demo:** `python run.py demo --fault 1`
- **Live Web Dashboard:** `python -m dashboard` (opens incident timeline, clickable agent trace, and recovery charts)
- **Offline Backup Video & Replay:**
  - Pre-recorded backup video: `results/demo_backup_video.gif`, `results/demo_backup_video.webp`, `results/demo_backup_video.html`
  - Offline replay command: `python -m bench.offline_replay`
  - Frozen benchmark results & charts: `results/final.json`, `results/final_results_page.html`, `results/final_charts/`
