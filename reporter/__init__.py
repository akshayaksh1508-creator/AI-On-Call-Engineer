"""reporter component package.

Owner: Person B (Brain & Trust)
Provides Slack webhook alerting, investigation reporting, interactive approvals,
GitHub remediation pull request lifecycle management, and escalation summaries.
"""

from reporter.escalation import (
    EscalationGenerator,
    EscalationSummary,
    EvidenceLink,
    HypothesisSummary,
)
from reporter.github_pr import GitHubPRClient, format_remediation_pr_body
from reporter.slack import SlackReporter

__all__ = [
    "EscalationGenerator",
    "EscalationSummary",
    "EvidenceLink",
    "GitHubPRClient",
    "HypothesisSummary",
    "SlackReporter",
    "format_remediation_pr_body",
]
