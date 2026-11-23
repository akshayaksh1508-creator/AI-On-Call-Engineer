# Day 3 code drop (Person A + Person B)

Unzip at the **repo root**. All files are new (nothing overwrites Day 1/2 files). If a path already exists, keep yours and compare.

## What is inside

| Task | Owner | Files |
|---|---|---|
| A1 Deployer + rollback + change events | A | `deployer/changes.py`, `runners.py`, `release_manager.py`, `router.py` |
| A2 Repo tools (git_log, git_diff, read_file) | A | `platform_api/repo_tools.py`, `repo_router.py` |
| A3 Faults 6-10 (2 cross-service) | A | `faults/env_faults.py`, `faults/runtime_flags.py`, `faults/specs/fault_06..10.yaml` |
| A4 RCA-only bench script | A | `bench/rca_bench.py` |
| B1 RCA strategy + investigator | B | `agent/rca.py`, `rca_strategy.py`, `log_clustering.py`, `rca_time.py` |
| B2 RCA evaluator | B | `agent/rca_evaluator.py` |
| B3 Prompt iterations v1-v3 + change log | B | `agent/prompt_iter.py`, `agent/synthetic_bundles.py`, `agent/bundle_client.py` |
| B4 Cross-service reasoning | B | `rank_suspects` in `rca_strategy.py` (upstream-first ranking) |
| Tests | both | `tests/deployer`, `tests/platform_api`, `tests/faults`, `tests/bench`, `tests/agent` |

Install once: `pip install pyyaml anthropic fastapi pydantic pytest`

## Run the tests (no Docker, no API key needed)

```
python -m pytest tests -q
# or one file at a time without pytest:
python tests/deployer/test_release_manager.py
```
Verified here with plain `unittest`: 40 tests pass. The FastAPI routers, `ComposeRunner` against real Docker, and `AnthropicLLM` against the real API were NOT run here; test them as in "Integration steps".

## Integration steps

### Person A
1. **Compose file**: each service must read its release dir and version so the deployer can rebuild it. Example for payments:
   ```yaml
   payments:
     build:
       context: ${PAYMENTS_RELEASE_DIR:-../target-app}/payments
     environment:
       APP_VERSION: ${PAYMENTS_VERSION:-dev}
   ```
   `/health` should return JSON with `"version": APP_VERSION` so the runner can confirm the new version is live.
2. **Mount routers** in your Platform API app:
   ```python
   from deployer.changes import ChangeLog
   from deployer.runners import ComposeRunner
   from deployer.release_manager import ReleaseManager
   from deployer.router import make_router
   from platform_api.repo_tools import RepoTools
   from platform_api.repo_router import make_repo_router

   changelog = ChangeLog("data/changes.jsonl")
   runner = ComposeRunner("infra/docker-compose.yml", health_urls={"gateway": "http://localhost:8080/health"})
   manager = ReleaseManager(".", "data/deploy_state.json", changelog, runner, app_subdir="target-app")
   app.include_router(make_router(manager, changelog))
   app.include_router(make_repo_router(RepoTools(".", root_subdir="target-app")))
   ```
   If you already have `/changes`, keep one of them (this router's `/changes` reads the same feed the injector writes).
   Run once per service at startup: `manager.bootstrap("payments", "HEAD")`.
3. **Wire fault flags into the services** (faults 6-10). Copy `faults/runtime_flags.py` next to each service:
   - payments, before building a response: `delay_ms("PAYMENTS_DB_QUERY_DELAY_MS")` and `payload = payments_response(payload)`
   - orders, discount code path: `if env_str("ORDERS_DISCOUNT_ENGINE","v1") == "v2": pct = order.discount.percent` (fails on None)
   - orders, DB pool: `pool_size = env_int("ORDERS_DB_POOL_SIZE", 10)`
   - gateway, upstream calls: `timeout = env_int("GATEWAY_UPSTREAM_TIMEOUT_MS", 2000) / 1000`
   Then make the compose file read an optional override: run with `-f infra/docker-compose.yml -f infra/docker-compose.faults.yml` (the injector passes both).
4. **Bench**: `python -m bench.rca_bench --faults fault_06,fault_07,fault_08,fault_09,fault_10 --no-llm`.
   It assumes `GET <platform-url>/incidents` returns the detector's incidents and `agent.platform_client:LivePlatformClient(base_url)` exists (B's Day 2 client). Change `--client module:callable` if yours is named differently.
5. Add to `.gitignore`: `.releases/`, `data/`, `infra/docker-compose.faults.yml`.

### Person B
1. Your Day 2 client must expose methods named like the tools: `query_logs, query_metrics, list_changes, git_log, git_diff, read_file, service_map, search_past_incidents`. If names differ, add a thin adapter class.
2. Heuristic baseline (free, no API): `python -m agent.prompt_iter --synthetic`.
3. With the LLM: `export ANTHROPIC_API_KEY=...` then `python -m agent.prompt_iter --bundles-dir tests/fixtures/bundles --versions v1 v2 v3 --llm anthropic`. Each run appends a row (with delta) to `results/prompt_changelog.md`.
4. Ask A for **real** bundles (JSON, schema in `agent/bundle_client.py`) recorded from faults 6-10; copy them to `tests/fixtures/bundles/`.
5. Model name comes from `ANTHROPIC_MODEL` (default `claude-sonnet-4-6`). Cost uses `PRICE_IN_PER_M` / `PRICE_OUT_PER_M` (defaults 3 and 15 USD per million tokens: set to current pricing).
6. If your Day 2 tool loop already works, keep it and reuse only `rca_strategy.py`, `log_clustering.py`, `rca_evaluator.py`.

## Day 3 gate checklist (copy into your standup)

- [ ] A1: deploy of a bad ref changes the version within 60 s; rollback restores it; events appear in `/changes` in order
- [ ] A2: `../` path rejected; culprit commit diff returned; `.env` not readable
- [ ] A3: faults 6-10 each apply and revert, detector fires, 2 cross-service faults show the symptom in a different service than the culprit
- [ ] A4: bench runs all 5 faults unattended and leaves the stack healthy
- [ ] B1: first tool call of every run is `list_changes`
- [ ] B2: evaluator run on real bundles writes `results/rca_day3.json`
- [ ] B3: `results/prompt_changelog.md` has v1, v2, v3 rows
- [ ] B4: at least 1 of 2 cross-service faults names the upstream service as top-1

## Honest notes

- The 5/5 heuristic score on `synthetic_bundles.py` is a smoke test on data designed by us. Report only numbers from real recorded runs.
- Faults 6-10 are config/feature-flag changes (realistic, and they show up in the change feed). Code-bug faults 1-5 stay with your Day 2 injector.
- `read_file`/`git_diff` refuse `.env`, keys and anything named like secrets; keep that deny list when you extend them.
