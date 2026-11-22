#!/usr/bin/env python3
"""NightShift - Cross-platform runner and CLI for Monorepo Tasks.

Supports commands: up, test, demo, reset, lint, check-owners.
Can be invoked directly via `python run.py <command>` or via `make <command>`.
"""

import argparse
import ast
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

# Components mandated by Section 5 & Section 14
EXPECTED_COMPONENTS = {
    "shared": ["contracts"],
    "person-a": [
        "target-app",
        "infra",
        "faults",
        "detector",
        "platform_api",
        "deployer",
        "verifier",
        "bench",
    ],
    "person-b": [
        "agent",
        "fixer",
        "memory",
        "safety",
        "reporter",
        "dashboard",
        "pitch",
        "orchestrator",
    ],
}


def cmd_up(args: argparse.Namespace) -> int:
    """Start target app, platform services, and infrastructure."""
    print("==> [UP] Initializing NightShift environment...")

    env_file = ROOT_DIR / ".env"
    env_example = ROOT_DIR / ".env.example"
    if not env_file.exists():
        if env_example.exists():
            print(f"Creating .env from {env_example.name}...")
            shutil.copyfile(env_example, env_file)
        else:
            print("WARNING: .env.example not found!", file=sys.stderr)

    compose_file = ROOT_DIR / "infra" / "docker-compose.yml"
    if compose_file.exists():
        print(f"Starting Docker Compose services from {compose_file}...")
        res = subprocess.run(["docker", "compose", "-f", str(compose_file), "up", "-d"])
        return res.returncode
    else:
        print("Note: infra/docker-compose.yml will be created in Task A2.")
        print("Environment configuration and monorepo directories verified.")
        return 0


def cmd_lint(args: argparse.Namespace) -> int:
    """Run linting and syntax/ast checks across repository."""
    print("==> [LINT] Checking Python source code and configs...")
    errors = 0

    # 1. Check if ruff or flake8 is available
    ruff_bin = shutil.which("ruff")
    if ruff_bin:
        print("Running ruff...")
        res = subprocess.run([ruff_bin, "check", str(ROOT_DIR)])
        if res.returncode != 0:
            errors += 1
    else:
        print("Note: ruff CLI not in PATH. Running built-in Python AST validator...")

    # Built-in Python AST syntax check for all .py files
    py_files = list(ROOT_DIR.rglob("*.py"))
    # Exclude virtual environments
    py_files = [
        f for f in py_files
        if not any(part in (".venv", "venv", "env", "build", "dist") for part in f.parts)
    ]

    for py_file in py_files:
        try:
            with open(py_file, "r", encoding="utf-8") as f:
                source = f.read()
            ast.parse(source, filename=str(py_file))
        except SyntaxError as e:
            print(f"SyntaxError in {py_file}:{e.lineno}: {e.msg}", file=sys.stderr)
            errors += 1

    if errors == 0:
        print(f"Linting passed: {len(py_files)} Python files parsed successfully.")
        return 0
    else:
        print(f"Linting failed with {errors} issue(s).", file=sys.stderr)
        return 1


def cmd_test(args: argparse.Namespace) -> int:
    """Run linters and the unit test suite."""
    print("==> [TEST] Running linter and unit tests...")
    lint_res = cmd_lint(args)
    if lint_res != 0:
        return lint_res

    # Discover and run tests in /tests and /target-app/tests
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(ROOT_DIR / "tests"), top_level_dir=str(ROOT_DIR), pattern="test_*.py")
    target_app_tests = ROOT_DIR / "target-app" / "tests"
    if target_app_tests.exists():
        suite.addTests(loader.discover(start_dir=str(target_app_tests), top_level_dir=str(target_app_tests), pattern="test_*.py"))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


def cmd_demo(args: argparse.Namespace) -> int:
    """Run end-to-end incident demo loop for a specific FAULT."""
    fault_id = getattr(args, "fault", None)
    if not fault_id:
        print("ERROR: Fault ID required. Usage: make demo FAULT=<id> or python run.py demo --fault <id>", file=sys.stderr)
        return 1

    print(f"==> [DEMO] Triggering demo incident resolution for fault '{fault_id}'...")
    print(f"Checking for fault definition in faults/...")
    fault_file = ROOT_DIR / "faults" / f"fault_{fault_id}.yaml"
    if fault_file.exists():
        print(f"Found fault definition: {fault_file}")
    else:
        print(f"Fault definition not yet generated (expected in Tasks A3/A4/A5).")

    print("Demo execution pipeline will be wired in Day 6 (make demo FAULT=<id>).")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    """Clean all cache directories, worktrees, and stop docker containers."""
    print("==> [RESET] Cleaning repository caches and temporary state...")

    compose_file = ROOT_DIR / "infra" / "docker-compose.yml"
    if compose_file.exists():
        print("Stopping Docker containers...")
        subprocess.run(["docker", "compose", "-f", str(compose_file), "down", "-v", "--remove-orphans"])

    # Free local microservice ports if running natively
    if sys.platform == "win32":
        for port in [8080, 8081, 8082, 9090]:
            try:
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"],
                    capture_output=True, text=True, check=False
                )
                for line in res.stdout.strip().splitlines():
                    pid = line.strip()
                    if pid.isdigit() and int(pid) != os.getpid():
                        subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"], capture_output=True)
            except Exception:
                pass

    # Remove temporary caches
    patterns = ["__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache"]
    removed_count = 0
    for pattern in patterns:
        for path in ROOT_DIR.rglob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed_count += 1

    for log_file in ROOT_DIR.rglob("*.log"):
        try:
            log_file.unlink()
            removed_count += 1
        except Exception:
            pass

    print(f"Cleaned {removed_count} cache and transient directories/files.")
    return 0


def cmd_check_owners(args: argparse.Namespace) -> int:
    """Verify CODEOWNERS file enforces the directory ownership rules from Section 5."""
    print("==> [CODEOWNERS] Validating directory ownership policy...")

    codeowners_file = ROOT_DIR / ".github" / "CODEOWNERS"
    if not codeowners_file.exists():
        codeowners_file = ROOT_DIR / "CODEOWNERS"

    if not codeowners_file.exists():
        print("ERROR: CODEOWNERS file not found!", file=sys.stderr)
        return 1

    content = codeowners_file.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]

    ownership_map = {}
    for line in lines:
        parts = line.split()
        if len(parts) >= 2:
            path_pattern = parts[0].strip("/")
            owners = parts[1:]
            ownership_map[path_pattern] = owners

    errors = 0

    # 1. Verify shared contracts
    contracts_owners = ownership_map.get("contracts", [])
    if "@person-a" not in contracts_owners or "@person-b" not in contracts_owners:
        print("ERROR: /contracts/ must require approval from BOTH @person-a and @person-b", file=sys.stderr)
        errors += 1

    # 2. Verify Person A folders
    for comp in EXPECTED_COMPONENTS["person-a"]:
        owners = ownership_map.get(comp, [])
        if "@person-a" not in owners:
            print(f"ERROR: /{comp}/ must be owned by @person-a (got: {owners})", file=sys.stderr)
            errors += 1

    # 3. Verify Person B folders
    for comp in EXPECTED_COMPONENTS["person-b"]:
        owners = ownership_map.get(comp, [])
        if "@person-b" not in owners:
            print(f"ERROR: /{comp}/ must be owned by @person-b (got: {owners})", file=sys.stderr)
            errors += 1

    if errors == 0:
        print("CODEOWNERS validation passed: All Section 5 directories correctly assigned.")
        return 0
    else:
        print(f"CODEOWNERS validation failed with {errors} error(s).", file=sys.stderr)
        return 1


def cmd_traffic(args: argparse.Namespace) -> int:
    """Run the target app traffic generator."""
    from target_app.traffic_generator import TrafficGenerator
    rate = getattr(args, "rate", 10.0) or 10.0
    duration = getattr(args, "duration", None)
    target = getattr(args, "target", "http://127.0.0.1:8080/api/orders")
    gen = TrafficGenerator(target_url=target, rate=rate, duration=duration)
    return gen.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="NightShift Monorepo Command Dispatcher")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("up", help="Start target app & infra")
    subparsers.add_parser("test", help="Run tests and linters")
    subparsers.add_parser("lint", help="Run linting checks")
    subparsers.add_parser("reset", help="Reset caches & infra")
    subparsers.add_parser("check-owners", help="Check CODEOWNERS coverage")

    traffic_parser = subparsers.add_parser("traffic", help="Run steady traffic generator")
    traffic_parser.add_argument("--rate", "-r", type=float, default=10.0, help="Requests per second")
    traffic_parser.add_argument("--duration", "-d", type=float, default=None, help="Duration in seconds")
    traffic_parser.add_argument("--target", default="http://127.0.0.1:8080/api/orders", help="Target URL")

    demo_parser = subparsers.add_parser("demo", help="Run demo loop")
    demo_parser.add_argument("--fault", type=str, required=True, help="Fault ID to inject")

    args = parser.parse_args()

    commands = {
        "up": cmd_up,
        "test": cmd_test,
        "lint": cmd_lint,
        "demo": cmd_demo,
        "reset": cmd_reset,
        "check-owners": cmd_check_owners,
        "traffic": cmd_traffic,
    }

    handler = commands.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
