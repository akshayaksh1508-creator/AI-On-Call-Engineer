"""Fix proposal generation, deterministic demo recipes, and GitHub PR publishing."""
from __future__ import annotations
from pathlib import Path
import json, os, subprocess, urllib.request, urllib.error
from day4.contracts.models import FixProposal

class Fixer:
    def build_proposal(self, *, proposal_id, diff, fault_id, rationale, expected_metric_effect,
                       regression_test, evidence_ids, fix_type="patch", risk_tier="T2",
                       branch_name=None):
        return FixProposal(proposal_id, fix_type, diff, risk_tier, rationale,
                           expected_metric_effect, regression_test, evidence_ids,
                           fault_id, branch_name).validate()

    def prepare_branch(self, *, repo_path, branch, proposal: FixProposal, base="main"):
        """Create a proposal branch, apply its patch, and commit it in a disposable clone."""
        repo_path = Path(repo_path).resolve()
        subprocess.run(["git", "checkout", base], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "-b", branch], cwd=repo_path, check=True, capture_output=True)
        check = subprocess.run(["git", "apply", "--check", "-"], cwd=repo_path,
                               input=proposal.diff, text=True, capture_output=True)
        if check.returncode:
            raise RuntimeError("Proposal patch failed git apply --check: " + check.stderr)
        subprocess.run(["git", "apply", "-"], cwd=repo_path, input=proposal.diff,
                       text=True, check=True, capture_output=True)
        subprocess.run(["git", "add", "src/", "tests/"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"Fix {proposal.fault_id or proposal.proposal_id}"],
                       cwd=repo_path, check=True, capture_output=True)
        return {"branch": branch, "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repo_path, text=True).strip()}

    def publish_pull_request(self, *, repo, branch, base="main", title, proposal: FixProposal,
                             verification: dict, token=None, repo_path=None):
        """Push the proposal branch and open an idempotent PR using GitHub REST API.

        Requires a git remote named origin and GITHUB_TOKEN (repo contents + pull_requests).
        """
        token = token or os.getenv("GITHUB_TOKEN")
        if not token:
            raise RuntimeError("GITHUB_TOKEN is required to publish a GitHub pull request.")
        owner_repo = repo.removeprefix("https://github.com/").removesuffix(".git").strip("/")
        if owner_repo.count("/") != 1:
            raise ValueError("repo must be owner/name or a GitHub repository URL")
        subprocess.run(["git", "push", "-u", "origin", branch], check=True, cwd=Path(repo_path or Path.cwd()))
        api = f"https://api.github.com/repos/{owner_repo}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "AI-On-Call-Engineer-Day4"}
        def request(path, method="GET", body=None):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(api + path, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=20) as response:
                    return json.loads(response.read().decode())
            except urllib.error.HTTPError as exc:
                raise RuntimeError(f"GitHub API {exc.code}: {exc.read().decode()[:1000]}") from exc
        existing = request(f"/pulls?state=open&head={owner_repo.split('/')[0]}:{branch}")
        if existing:
            return {"created": False, "url": existing[0]["html_url"], "number": existing[0]["number"]}
        body = {
            "title": title, "head": branch, "base": base,
            "body": self._pr_body(proposal, verification)
        }
        pr = request("/pulls", "POST", body)
        return {"created": True, "url": pr["html_url"], "number": pr["number"]}

    @staticmethod
    def _pr_body(proposal, verification):
        return (
            "## Root cause and rationale\n" + proposal.rationale +
            "\n\n## Evidence IDs\n" + "\n".join(f"- `{x}`" for x in proposal.evidence_ids) +
            "\n\n## Proposed fix\n```diff\n" + proposal.diff[:12000] + "\n```" +
            "\n\n## Expected metric effect\n" + proposal.expected_metric_effect +
            "\n\n## Regression test\n" + proposal.regression_test +
            "\n\n## Sandbox verification\n" +
            f"- Verdict: **{verification.get('verdict', 'not-run')}**\n" +
            f"- Unit tests passed: `{verification.get('tests_passed', False)}`\n" +
            f"- Reproduction fixed: `{verification.get('repro_fixed', False)}`\n" +
            f"- Worktree cleaned: `{verification.get('worktree_cleaned', False)}`\n"
        )
