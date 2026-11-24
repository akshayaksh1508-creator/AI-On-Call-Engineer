from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
from day4.fixer.demo_catalog import DemoCatalog, TARGET
from day4.verifier.sandbox import SandboxVerifier

def ensure_git_repo():
    if not (TARGET / ".git").exists():
        subprocess.run(["git", "init", "-b", "main"], cwd=TARGET, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "day4-demo@example.invalid"], cwd=TARGET, check=True)
        subprocess.run(["git", "config", "user.name", "Day 4 Demo"], cwd=TARGET, check=True)
        subprocess.run(["git", "add", "."], cwd=TARGET, check=True)
        subprocess.run(["git", "commit", "-m", "Seed five reproducible code faults"], cwd=TARGET, check=True, capture_output=True)

def verify(fault_id):
    ensure_git_repo()
    proposal = DemoCatalog().proposal(fault_id)
    module = f"tests.test_{fault_id}"
    verifier = SandboxVerifier(TARGET, allowed_paths=("src/", "tests/"), forbidden_paths=(".env", ".git/", "secrets/"))
    result = verifier.verify(
        proposal.diff,
        [sys.executable, "-m", "unittest", module],
        [sys.executable, "scripts/reproduce.py", fault_id]
    )
    return proposal, result

def main():
    parser = argparse.ArgumentParser(description="AI On-Call Engineer Day 4 fixer/verifier demo")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="initialize the five-fault sample git repository")
    v = sub.add_parser("verify", help="generate and sandbox-verify one demo fix")
    v.add_argument("fault_id", choices=[f"fault_0{i}" for i in range(1,6)])
    sub.add_parser("benchmark", help="verify all five simple code faults and calculate fix rate")
    p = sub.add_parser("proposal", help="print a FixProposal JSON")
    p.add_argument("fault_id", choices=[f"fault_0{i}" for i in range(1,6)])
    pr = sub.add_parser("publish-pr", help="prepare a branch and open a GitHub PR (requires token and origin remote)")
    pr.add_argument("fault_id", choices=[f"fault_0{i}" for i in range(1,6)])
    pr.add_argument("--repo", required=True, help="GitHub owner/name")
    pr.add_argument("--base", default="main")
    args = parser.parse_args()
    if args.command == "init":
        ensure_git_repo()
        print(f"Initialized sample target repo: {TARGET}")
    elif args.command == "proposal":
        print(DemoCatalog().proposal(args.fault_id).to_json())
    elif args.command == "verify":
        proposal, result = verify(args.fault_id)
        print(json.dumps({"proposal": proposal.to_dict(), "verification": result.to_dict()}, indent=2))
        raise SystemExit(0 if result.verdict == "pass" else 1)
    elif args.command == "publish-pr":
        from day4.fixer.fixer import Fixer
        proposal, result = verify(args.fault_id)
        if result.verdict != "pass":
            raise SystemExit("Refusing to open a PR: sandbox verification did not pass.")
        fixer = Fixer()
        prepared = fixer.prepare_branch(repo_path=TARGET, branch=proposal.branch_name,
                                        proposal=proposal, base=args.base)
        pr_result = fixer.publish_pull_request(
            repo=args.repo, branch=proposal.branch_name, base=args.base,
            title=f"Fix {args.fault_id}", proposal=proposal,
            verification=result.to_dict(), repo_path=TARGET
        )
        print(json.dumps({"prepared": prepared, "pull_request": pr_result}, indent=2))
    elif args.command == "benchmark":
        results = []
        for i in range(1, 6):
            fid = f"fault_{i:02d}"
            proposal, result = verify(fid)
            results.append({"fault_id": fid, "verdict": result.verdict,
                            "tests_passed": result.tests_passed, "repro_fixed": result.repro_fixed,
                            "worktree_cleaned": result.worktree_cleaned})
        passed = sum(x["verdict"] == "pass" for x in results)
        report = {"passed": passed, "total": 5, "fix_rate": round(passed/5, 2), "exit_gate_met": passed >= 3, "results": results}
        Path("day4_benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if passed >= 3 else 1)
if __name__ == "__main__":
    main()
