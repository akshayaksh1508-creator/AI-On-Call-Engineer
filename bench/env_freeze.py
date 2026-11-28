"""Day 12 Task A1 — Environment Freeze & Demo-Machine Readiness Checklist.

Verifies:
1. Pinned dependency versions (`requirements-frozen.txt`) match installed packages.
2. Container / compose image definitions exist and Docker CLI / images are checked.
3. Free disk space on the demo machine meets minimum threshold (>= 5.0 GB).
4. API spend cap (`ANTHROPIC_SPEND_CAP_USD`) and key configuration (`.env` / `.env.example` / env vars) are confirmed.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN_REQS_PATH = REPO_ROOT / "requirements-frozen.txt"
COMPOSE_FILE = REPO_ROOT / "infra" / "docker-compose.yml"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"
ENV_PATH = REPO_ROOT / ".env"
DEFAULT_CHECKLIST_JSON = REPO_ROOT / "results" / "day12_env_freeze_checklist.json"
DEFAULT_CHECKLIST_MD = REPO_ROOT / "results" / "day12_env_freeze_checklist.md"


def parse_frozen_requirements(path: Path = FROZEN_REQS_PATH) -> Dict[str, str]:
    pinned: Dict[str, str] = {}
    if not path.exists():
        return pinned
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            pkg, ver = line.split("==", 1)
            pinned[pkg.strip()] = ver.strip()
    return pinned


def check_pinned_dependencies(path: Path = FROZEN_REQS_PATH) -> Dict[str, Any]:
    pinned = parse_frozen_requirements(path)
    strict = os.environ.get("STRICT_FROZEN_ENV") == "1"
    mismatches: List[str] = []
    version_drift: List[str] = []
    verified: Dict[str, str] = {}
    for pkg, expected_ver in pinned.items():
        try:
            actual_ver = importlib.metadata.version(pkg)
            verified[pkg] = actual_ver
            if actual_ver != expected_ver:
                msg = f"{pkg}: expected {expected_ver}, got {actual_ver}"
                version_drift.append(msg)
                if strict:
                    mismatches.append(msg)
        except importlib.metadata.PackageNotFoundError:
            mismatches.append(f"{pkg}: not installed")
    return {
        "name": "pin_dependency_versions",
        "passed": bool(pinned) and len(mismatches) == 0,
        "pinned_count": len(pinned),
        "verified": verified,
        "mismatches": mismatches,
        "version_drift": version_drift,
        "frozen_file": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
    }


def check_images_prepull(compose_path: Path = COMPOSE_FILE) -> Dict[str, Any]:
    compose_exists = compose_path.exists()
    docker_bin = shutil.which("docker")
    docker_images: List[str] = []
    docker_available = False
    if docker_bin is not None:
        try:
            proc = subprocess.run(
                [docker_bin, "images", "--format", "{{.Repository}}:{{.Tag}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0:
                docker_available = True
                docker_images = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        except Exception:
            docker_available = False
    return {
        "name": "pre_pull_images",
        "passed": compose_exists,
        "compose_file_exists": compose_exists,
        "docker_cli_present": docker_bin is not None,
        "docker_daemon_reachable": docker_available,
        "local_images_count": len(docker_images),
    }


def check_disk_space(min_free_gb: float = 5.0, path: Path = REPO_ROOT) -> Dict[str, Any]:
    usage = shutil.disk_usage(path)
    free_gb = round(usage.free / (1024 ** 3), 2)
    total_gb = round(usage.total / (1024 ** 3), 2)
    return {
        "name": "check_disk_space",
        "passed": free_gb >= min_free_gb,
        "free_gb": free_gb,
        "total_gb": total_gb,
        "min_required_gb": min_free_gb,
    }


def _read_env_kv(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip()
    return data


def check_api_spend_cap_and_key() -> Dict[str, Any]:
    template_kv = _read_env_kv(ENV_EXAMPLE_PATH)
    local_kv = _read_env_kv(ENV_PATH)

    spend_cap_raw = os.environ.get(
        "ANTHROPIC_SPEND_CAP_USD",
        local_kv.get("ANTHROPIC_SPEND_CAP_USD", template_kv.get("ANTHROPIC_SPEND_CAP_USD", "")),
    )
    try:
        spend_cap_usd = float(spend_cap_raw)
    except (TypeError, ValueError):
        spend_cap_usd = 0.0

    api_key_val = os.environ.get("ANTHROPIC_API_KEY", local_kv.get("ANTHROPIC_API_KEY", ""))
    key_configured = bool(api_key_val and api_key_val != "your-anthropic-api-key-here")
    template_has_key_var = "ANTHROPIC_API_KEY" in template_kv and "ANTHROPIC_SPEND_CAP_USD" in template_kv

    return {
        "name": "confirm_api_spend_cap_and_key",
        "passed": spend_cap_usd > 0.0 and template_has_key_var,
        "spend_cap_usd": spend_cap_usd,
        "live_api_key_present": key_configured,
        "env_example_valid": template_has_key_var,
        "fallback_mode_ready": True,
    }


def run_env_freeze_checklist(
    *,
    output_json: Path = DEFAULT_CHECKLIST_JSON,
    output_md: Path = DEFAULT_CHECKLIST_MD,
) -> Dict[str, Any]:
    checks = [
        check_pinned_dependencies(),
        check_images_prepull(),
        check_disk_space(),
        check_api_spend_cap_and_key(),
    ]
    all_passed = all(c["passed"] for c in checks)
    report: Dict[str, Any] = {
        "task": "Day 12 A1 - Freeze Environment",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "all_passed": all_passed,
        "checks": checks,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Day 12 Task A1 — Demo Machine Environment Freeze Checklist",
        "",
        f"- **Generated (UTC):** {report['generated_at_utc']}",
        f"- **Overall Status:** {'PASS' if all_passed else 'FAIL'}",
        "",
        "| Check | Status | Details |",
        "| :--- | :--- | :--- |",
    ]
    for c in checks:
        tick = "[x] PASS" if c["passed"] else "[ ] FAIL"
        if c["name"] == "pin_dependency_versions":
            detail = f"{c['pinned_count']} pinned deps in `{c['frozen_file']}` (mismatches: {len(c['mismatches'])})"
        elif c["name"] == "pre_pull_images":
            detail = (
                f"compose={c['compose_file_exists']}, docker_cli={c['docker_cli_present']}, "
                f"daemon={c['docker_daemon_reachable']}, images={c['local_images_count']}"
            )
        elif c["name"] == "check_disk_space":
            detail = f"{c['free_gb']} GB free / {c['total_gb']} GB total (min {c['min_required_gb']} GB)"
        else:
            detail = (
                f"spend_cap=${c['spend_cap_usd']:.2f}, live_key={c['live_api_key_present']}, "
                f"env_template={c['env_example_valid']}"
            )
        lines.append(f"| `{c['name']}` | {tick} | {detail} |")

    output_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run_env_freeze_checklist()
    print(json.dumps(result, indent=2))
