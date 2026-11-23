"""RCA-only benchmark runner (Day 3, A4).

For each fault: confirm healthy -> inject -> wait for the detector's incident ->
call the agent -> store the output -> revert -> wait until healthy again.
Output feeds agent/rca_evaluator.py (B) to compute top-1 / top-3 accuracy.

    python -m bench.rca_bench --faults fault_06,fault_07 --out results/rca_day3_runs.json

Needs the running stack, the detector's incident list and the agent entry point
`agent.rca.investigate(incident, client)`. Everything is injectable for tests.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable


class HttpIncidentSource:
    """Reads incidents from the Platform API (GET <base><path> -> list or {incidents: [...]})."""

    def __init__(self, base_url: str, path: str = "/incidents"):
        self.url = base_url.rstrip("/") + path

    def list(self) -> list[dict[str, Any]]:
        with urllib.request.urlopen(self.url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return data.get("incidents", []) if isinstance(data, dict) else data


def http_health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def wait_for(predicate: Callable[[], Any], timeout: float, interval: float = 2.0,
             sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.time):
    deadline = clock() + timeout
    while clock() < deadline:
        value = predicate()
        if value:
            return value
        sleep(interval)
    return None


def run_bench(
    fault_ids: list[str],
    injector,
    incidents,
    investigate_fn: Callable[[dict], dict],
    health_fn: Callable[[], bool],
    detect_timeout: float = 90.0,
    recover_timeout: float = 120.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for fid in fault_ids:
        rec: dict[str, Any] = {"fault_id": fid, "status": "ok"}
        try:
            if not wait_for(health_fn, recover_timeout, 2.0, sleep, clock):
                rec["status"] = "infra_error: not healthy before injection"
                runs.append(rec)
                continue
            seen = {i["id"] for i in incidents.list()}
            t_inject = clock()
            injector.apply(fid)

            def new_incident():
                for inc in incidents.list():
                    if inc["id"] not in seen:
                        return inc
                return None

            inc = wait_for(new_incident, detect_timeout, 2.0, sleep, clock)
            if not inc:
                rec["status"] = "detector_miss"
                rec["detect_timeout_s"] = detect_timeout
            else:
                t_detect = clock()
                rec["incident"] = inc
                rec["t_detect_s"] = round(t_detect - t_inject, 2)
                try:
                    out = investigate_fn(inc)
                    rec["output"] = out
                    rec["t_rca_s"] = round(clock() - t_inject, 2)
                except Exception as exc:  # agent crash must not stop the bench
                    rec["status"] = f"agent_error: {type(exc).__name__}: {exc}"
        finally:
            try:
                injector.revert(fid)
                if not wait_for(health_fn, recover_timeout, 2.0, sleep, clock):
                    rec["recovered"] = False
                else:
                    rec["recovered"] = True
            except Exception as exc:
                rec["recovered"] = False
                rec["revert_error"] = str(exc)
        runs.append(rec)
    return runs


def _load_callable(spec: str) -> Callable:
    mod, _, attr = spec.partition(":")
    return getattr(importlib.import_module(mod), attr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--faults", required=True, help="comma separated, e.g. fault_06,fault_07")
    ap.add_argument("--out", default="results/rca_day3_runs.json")
    ap.add_argument("--platform-url", default=os.getenv("PLATFORM_API_URL", "http://localhost:8000"))
    ap.add_argument("--health-url", default=os.getenv("GATEWAY_HEALTH_URL", "http://localhost:8080/health"))
    ap.add_argument("--client", default=os.getenv("RCA_CLIENT_FACTORY", "agent.platform_client:LivePlatformClient"),
                    help="module:callable that returns a PlatformClient given base_url")
    ap.add_argument("--compose-file", default=os.getenv("COMPOSE_FILE", "infra/docker-compose.yml"))
    ap.add_argument("--specs-dir", default="faults/specs")
    ap.add_argument("--no-llm", action="store_true", help="heuristic-only baseline (no API cost)")
    args = ap.parse_args()

    from agent.rca import AnthropicLLM, investigate
    from deployer.changes import ChangeLog
    from deployer.runners import ComposeRunner
    from faults.env_faults import EnvFaultInjector

    changelog = ChangeLog(os.getenv("CHANGELOG_PATH", "data/changes.jsonl"))
    runner = ComposeRunner(args.compose_file)
    injector = EnvFaultInjector(
        args.specs_dir, runner, args.compose_file,
        override_path="infra/docker-compose.faults.yml", state_path="data/faults_state.json",
        changelog=changelog,
    )
    client = _load_callable(args.client)(args.platform_url)
    llm = None if args.no_llm else AnthropicLLM()
    runs = run_bench(
        [f.strip() for f in args.faults.split(",") if f.strip()],
        injector,
        HttpIncidentSource(args.platform_url),
        lambda inc: investigate(inc, client, llm=llm),
        lambda: http_health(args.health_url),
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(runs, indent=2, default=str))
    ok = sum(1 for r in runs if r["status"] == "ok")
    print(f"{ok}/{len(runs)} runs completed -> {args.out}")


if __name__ == "__main__":
    main()
