"""reporter component package.

Owner: Person B (Brain & Trust)
Provides Slack webhook alerting, investigation reporting, interactive approvals,
and GitHub remediation pull request lifecycle management.
"""

from reporter.slack import SlackReporter
from reporter.github_pr import GitHubPRClient, format_remediation_pr_body

__all__ = [
    "SlackReporter",
    "GitHubPRClient",
    "format_remediation_pr_body",
]
