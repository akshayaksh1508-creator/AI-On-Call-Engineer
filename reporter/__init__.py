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
from reporter.final_report import FinalReportPublisher, FinalReportResult, generate_recovery_graph_svg
from reporter.github_pr import GitHubPRClient, format_remediation_pr_body
from reporter.postmortem import PostmortemGenerator, PostmortemReport
from reporter.slack import SlackReporter

__all__ = [
    "EscalationGenerator",
    "EscalationSummary",
    "EvidenceLink",
    "FinalReportPublisher",
    "FinalReportResult",
    "GitHubPRClient",
    "HypothesisSummary",
    "PostmortemGenerator",
    "PostmortemReport",
    "SlackReporter",
    "format_remediation_pr_body",
    "generate_recovery_graph_svg",
]
