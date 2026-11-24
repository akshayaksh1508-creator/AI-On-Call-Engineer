"""Slack Webhook Integration Client for Incident Reporting and Approvals.

Owner: Person B (Brain & Trust)
Provides structured Slack alerting, incident investigation reports, state transitions,
and interactive remediation approval requests (Day 1 Task B4 & Day 6 Safety).
Supports live webhooks and zero-dependency mock mode for offline testing.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from contracts.models import Evidence, FixProposal, Hypothesis, Incident

logger = logging.getLogger("reporter.slack")


class SlackReporter:
    """Slack integration client for dispatching incident notifications and reports."""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        mock: Optional[bool] = None,
    ):
        self.webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL", "")
        
        is_placeholder = (
            not self.webhook_url
            or "YOUR/SLACK/WEBHOOK" in self.webhook_url
            or "hooks.slack.com/services/YOUR" in self.webhook_url
            or "placeholder" in self.webhook_url.lower()
        )
        if mock is not None:
            self.mock = mock
        elif os.environ.get("SLACK_MOCK", "").lower() in ("1", "true", "yes"):
            self.mock = True
        elif is_placeholder:
            self.mock = True
        else:
            self.mock = False

        # In-memory history for test assertions and audit trails
        self.sent_messages: List[Dict[str, Any]] = []

    def send_message(
        self,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Send a formatted message or Slack Block Kit payload to the webhook."""
        payload: Dict[str, Any] = {"text": text}
        if blocks:
            payload["blocks"] = blocks

        if self.mock:
            record = {
                "ok": True,
                "status": "mock_delivered",
                "payload": payload,
            }
            self.sent_messages.append(record)
            logger.info("Mock Slack webhook dispatched: %s", text[:120])
            return record

        # Live dispatch via urllib
        req = urllib.request.Request(
            self.webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10.0) as response:
                status_code = response.getcode()
                body = response.read().decode("utf-8")
                record = {
                    "ok": status_code == 200,
                    "status": "delivered" if status_code == 200 else f"http_{status_code}",
                    "response": body,
                    "payload": payload,
                }
                self.sent_messages.append(record)
                return record
        except urllib.error.URLError as exc:
            logger.error("Slack webhook delivery failed: %s", exc)
            record = {
                "ok": False,
                "status": "error",
                "error": str(exc),
                "payload": payload,
            }
            self.sent_messages.append(record)
            return record

    def send_incident_alert(self, incident: Incident) -> Dict[str, Any]:
        """Send high-priority alert notification when a new incident is detected."""
        text = f":rotating_light: *[NIGHTSHIFT INCIDENT ALERT]* `{incident.id}` on `{incident.service}`"
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Incident Alert: {incident.id}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Service:*\n`{incident.service}`"},
                    {"type": "mrkdwn", "text": f"*Status:*\n`{incident.status.upper()}`"},
                    {"type": "mrkdwn", "text": f"*Started At:*\n{incident.started_at}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Triggered Alerts:*\n{', '.join(incident.alerts) if incident.alerts else 'None'}",
                    },
                ],
            },
        ]
        if incident.symptoms:
            symptoms_formatted = "\n".join(f"• {s}" for s in incident.symptoms)
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Observed Symptoms:*\n{symptoms_formatted}"},
            })
        return self.send_message(text=text, blocks=blocks)

    def send_state_change(
        self,
        incident_id: str,
        old_state: str,
        new_state: str,
        details: str = "",
    ) -> Dict[str, Any]:
        """Send notification when an incident transitions states (investigating -> mitigating -> verified)."""
        emoji_map = {
            "open": ":warning:",
            "investigating": ":mag:",
            "mitigating": ":wrench:",
            "verifying": ":hourglass_flowing_sand:",
            "resolved": ":white_check_mark:",
            "escalated": ":scream:",
        }
        emoji = emoji_map.get(new_state.lower(), ":information_source:")
        text = f"{emoji} Incident `{incident_id}` transitioned: `{old_state}` -> `{new_state}`"
        if details:
            text += f"\n> {details}"
        return self.send_message(text=text)

    def send_investigation_report(
        self,
        incident_id: str,
        summary: str,
        hypotheses: List[Hypothesis],
        evidence: List[Evidence],
    ) -> Dict[str, Any]:
        """Send comprehensive root cause analysis report with evidence citations."""
        text = f":bar_chart: *RCA Investigation Report* for `{incident_id}`"
        blocks: List[Dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Investigation Findings: {incident_id}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Executive Summary:*\n{summary}"},
            },
        ]

        if hypotheses:
            hypo_lines = []
            for i, h in enumerate(hypotheses[:3], 1):
                citations = " ".join(f"`[{eid}]`" for eid in h.evidence_ids) if h.evidence_ids else "`[GUESS]`"
                culprit = f" (Culprit: `{h.culprit_change}`)" if h.culprit_change else ""
                hypo_lines.append(
                    f"*{i}. [{h.category.upper()}] Confidence: {h.confidence:.0%}* {citations}{culprit}\n"
                    f">{h.cause}"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Ranked Root Cause Hypotheses:*\n" + "\n\n".join(hypo_lines)},
            })

        if evidence:
            ev_lines = []
            for ev in evidence[:5]:
                ev_lines.append(f"• `[{ev.id}]` *{ev.type.upper()}* `{ev.ref}`: _{ev.excerpt[:100]}_")
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Empirical Evidence Pool:*\n" + "\n".join(ev_lines)},
            })

        return self.send_message(text=text, blocks=blocks)

    def send_approval_request(
        self,
        incident_id: str,
        proposal: FixProposal,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send interactive remediation sign-off request with Approve and Reject buttons."""
        req_id = request_id or f"req_{incident_id}"
        text = f":hand: *[APPROVAL REQUIRED]* Fix proposal for `{incident_id}` ({proposal.risk_tier})"
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Remediation Sign-off Required: {incident_id}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Risk Tier:*\n`{proposal.risk_tier}`"},
                    {"type": "mrkdwn", "text": f"*Remediation Type:*\n`{proposal.type}`"},
                    {"type": "mrkdwn", "text": f"*Target Service:*\n`{proposal.target_service}`"},
                    {"type": "mrkdwn", "text": f"*Expected Metric Effect:*\n{proposal.expected_metric_effect}"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Rationale:*\n{proposal.rationale}"},
            },
        ]
        if proposal.diff:
            diff_preview = proposal.diff[:300] + ("\n..." if len(proposal.diff) > 300 else "")
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Proposed Diff:*\n```\n{diff_preview}\n```"},
            })

        # Add interactive Approve and Reject buttons
        blocks.append({
            "type": "actions",
            "block_id": f"approval_actions_{req_id}",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve Fix"},
                    "style": "primary",
                    "action_id": "approve_fix",
                    "value": req_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject Fix"},
                    "style": "danger",
                    "action_id": "reject_fix",
                    "value": req_id,
                },
            ],
        })
        return self.send_message(text=text, blocks=blocks)

    def send_escalation_alert(
        self,
        incident_id: str,
        reason: str,
        proposal: Optional[FixProposal] = None,
    ) -> Dict[str, Any]:
        """Send notification when an approval times out or incident escalates."""
        text = f":rotating_light: *[ESCALATED]* Incident `{incident_id}`: {reason}"
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Escalation Alert: {incident_id}"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Reason:*\n{reason}"},
            },
        ]
        if proposal:
            blocks.append({
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Risk Tier:*\n`{proposal.risk_tier}`"},
                    {"type": "mrkdwn", "text": f"*Target Service:*\n`{proposal.target_service}`"},
                ],
            })
        return self.send_message(text=text, blocks=blocks)

