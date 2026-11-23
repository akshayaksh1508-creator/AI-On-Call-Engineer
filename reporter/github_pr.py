"""GitHub Sandbox Pull Request Client.

Owner: Person B (Brain & Trust)
Enables NightShift to open remediation pull requests against the GitHub sandbox repository,
inspect PR status, attach verification summaries, and close PRs (Day 1 Task B4 & Day 4 Task B4).
Supports live GitHub REST API and offline mock mode when running without tokens.
"""

from datetime import datetime, timezone
import json
import logging
import os
import urllib.parse
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.request
from contracts.models import FixProposal, Hypothesis, Incident, VerificationResult

logger = logging.getLogger("reporter.github")


class GitHubPRClient:
    """Client for managing remediation pull requests on the GitHub sandbox repository."""

    def __init__(
        self,
        token: Optional[str] = None,
        repo: Optional[str] = None,
        mock: Optional[bool] = None,
    ):
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.repo = repo or os.environ.get("GITHUB_SANDBOX_REPO", "nightshift/target-app-sandbox")

        is_placeholder = (
            not self.token
            or "your_github_sandbox_token" in self.token
            or "ghp_your" in self.token
            or "placeholder" in self.token.lower()
        )
        if mock is not None:
            self.mock = mock
        elif os.environ.get("GITHUB_MOCK", "").lower() in ("1", "true", "yes"):
            self.mock = True
        elif is_placeholder:
            self.mock = True
        else:
            self.mock = False

        # In-memory mock state for deterministic testing & offline CI
        self._mock_prs: Dict[int, Dict[str, Any]] = {}
        self._mock_comments: Dict[int, List[Dict[str, Any]]] = {}
        self._next_pr_number: int = 101

    def create_or_update_pr(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        draft: bool = False,
    ) -> Dict[str, Any]:
        """Create a new remediation PR or update existing PR from the head branch."""
        if self.mock:
            # Check for existing PR with same head and base branch
            for pr in self._mock_prs.values():
                if pr["head"]["ref"] == head_branch and pr["base"]["ref"] == base_branch and pr["state"] == "open":
                    pr["title"] = title
                    pr["body"] = body
                    pr["updated_at"] = datetime.now(timezone.utc).isoformat()
                    logger.info("Updated existing mock PR #%d (%s)", pr["number"], head_branch)
                    return pr

            pr_number = self._next_pr_number
            self._next_pr_number += 1
            now = datetime.now(timezone.utc).isoformat()
            pr_data = {
                "number": pr_number,
                "id": 900000 + pr_number,
                "html_url": f"https://github.com/{self.repo}/pull/{pr_number}",
                "title": title,
                "body": body,
                "state": "open",
                "draft": draft,
                "head": {"ref": head_branch, "label": f"{self.repo.split('/')[0]}:{head_branch}"},
                "base": {"ref": base_branch, "label": f"{self.repo.split('/')[0]}:{base_branch}"},
                "created_at": now,
                "updated_at": now,
                "closed_at": None,
                "merged_at": None,
                "comments_count": 0,
            }
            self._mock_prs[pr_number] = pr_data
            self._mock_comments[pr_number] = []
            logger.info("Opened new mock PR #%d (%s -> %s)", pr_number, head_branch, base_branch)
            return pr_data

        # GitHub rejects duplicate open PRs for the same head/base. Look one up
        # first so a retry updates the existing remediation request.
        owner = self.repo.split("/", 1)[0]
        query = urllib.parse.urlencode(
            {"state": "open", "head": f"{owner}:{head_branch}", "base": base_branch}
        )
        matches = self._http_request(
            url=f"https://api.github.com/repos/{self.repo}/pulls?{query}", method="GET"
        )
        if matches:
            existing = matches[0]
            number = existing["number"]
            return self._http_request(
                url=f"https://api.github.com/repos/{self.repo}/pulls/{number}",
                method="PATCH",
                payload={"title": title, "body": body, "base": base_branch, "draft": draft},
            )

        # Live GitHub REST API v3
        url = f"https://api.github.com/repos/{self.repo}/pulls"
        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
            "draft": draft,
        }
        return self._http_request(url=url, method="POST", payload=payload)

    def create_remediation_pr(
        self,
        incident: Incident,
        hypothesis: Hypothesis,
        proposal: FixProposal,
        head_branch: str,
        verification: Optional[VerificationResult] = None,
        base_branch: str = "main",
    ) -> Dict[str, Any]:
        """Open or update an idempotent PR containing the complete remediation record."""
        title = f"fix({incident.service}): remediate {incident.id}"
        body = format_remediation_pr_body(incident, hypothesis, proposal, verification)
        return self.create_or_update_pr(title, body, head_branch, base_branch)

    def close_pr(self, pr_number: int) -> Dict[str, Any]:
        """Close an open remediation PR without merging."""
        if self.mock:
            if pr_number not in self._mock_prs:
                raise KeyError(f"Mock PR #{pr_number} not found.")
            pr = self._mock_prs[pr_number]
            pr["state"] = "closed"
            pr["closed_at"] = datetime.now(timezone.utc).isoformat()
            logger.info("Closed mock PR #%d", pr_number)
            return pr

        url = f"https://api.github.com/repos/{self.repo}/pulls/{pr_number}"
        return self._http_request(url=url, method="PATCH", payload={"state": "closed"})

    def get_pr(self, pr_number: int) -> Dict[str, Any]:
        """Retrieve pull request metadata by PR number."""
        if self.mock:
            if pr_number not in self._mock_prs:
                raise KeyError(f"Mock PR #{pr_number} not found.")
            return self._mock_prs[pr_number]

        url = f"https://api.github.com/repos/{self.repo}/pulls/{pr_number}"
        return self._http_request(url=url, method="GET")

    def add_comment(self, pr_number: int, comment: str) -> Dict[str, Any]:
        """Add a comment (e.g. verification test run or metric recovery) to a PR."""
        if self.mock:
            if pr_number not in self._mock_prs:
                raise KeyError(f"Mock PR #{pr_number} not found.")
            record = {
                "id": len(self._mock_comments[pr_number]) + 1,
                "body": comment,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._mock_comments[pr_number].append(record)
            self._mock_prs[pr_number]["comments_count"] = len(self._mock_comments[pr_number])
            logger.info("Added comment to mock PR #%d", pr_number)
            return record

        url = f"https://api.github.com/repos/{self.repo}/issues/{pr_number}/comments"
        return self._http_request(url=url, method="POST", payload={"body": comment})

    def _http_request(
        self,
        url: str,
        method: str = "GET",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute authenticated HTTP request against GitHub REST API."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "NightShift-OnCall-Agent",
        }
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url=url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                content = resp.read().decode("utf-8")
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8")
            logger.error("GitHub API HTTPError %d: %s", exc.code, err_body)
            raise RuntimeError(f"GitHub API Error {exc.code}: {err_body}") from exc
        except urllib.error.URLError as exc:
            logger.error("GitHub API URLError: %s", exc)
            raise RuntimeError(f"GitHub connection failed: {exc}") from exc


def format_remediation_pr_body(
    incident: Incident,
    hypothesis: Hypothesis,
    proposal: FixProposal,
    verification: Optional[VerificationResult] = None,
) -> str:
    """Format structured markdown PR description meeting Section 7 & Day 4 B4 rules:
    Must contain: Root cause explanation, Cited Evidence IDs, Expected Metric Effect, Test Results.
    """
    evidence_str = (
        ", ".join(f"`[{eid}]`" for eid in hypothesis.evidence_ids)
        if hypothesis.evidence_ids
        else "_[GUESS - No evidence cited]_"
    )

    culprit_str = f"`{hypothesis.culprit_change}`" if hypothesis.culprit_change else "_None detected_"

    body = f"""## :shield: NightShift Autonomous Remediation PR

### 1. Incident Overview
- **Incident ID:** `{incident.id}`
- **Target Service:** `{incident.service}`
- **Anomaly Detection:** `{incident.started_at}`
- **Observed Symptoms:** {', '.join(incident.symptoms)}

### 2. Root Cause Analysis
- **Category:** `{hypothesis.category.upper()}` (Confidence: **{hypothesis.confidence:.0%}**)
- **Empirical Evidence IDs:** {evidence_str}
- **Culprit Change:** {culprit_str}
- **Mechanism:**
> {hypothesis.cause}

### 3. Proposed Remediation
- **Remediation Type:** `{proposal.type}`
- **Risk Tier:** `{proposal.risk_tier}`
- **Rationale:** {proposal.rationale}
- **Expected Production Metric Effect:**
> {proposal.expected_metric_effect}
"""

    if verification:
        status_icon = ":white_check_mark:" if verification.verdict == "PASS" else ":x:"
        body += f"""
### 4. Automated Multi-Stage Verification
- **Verdict:** {status_icon} **{verification.verdict}**
- **Isolated Worktree Unit Tests:** {'PASSED' if verification.tests_passed else 'FAILED'}
- **Reproduction Script:** {'REPRO FIXED' if verification.repro_fixed else 'REPRO FAILED'}
- **Canary Error Rate:** `{verification.metric_before:.1%}` -> `{verification.metric_after:.1%}`
"""
    else:
        body += """
### 4. Verification Status
- **Sandbox unit tests:** Not run
- **Failing request reproduction:** Not run
- **Result:** Awaiting automated worktree and canary verification
"""

    body += "\n---\n*Authored autonomously by NightShift AI On-Call Engineer.*"
    return body.strip()
