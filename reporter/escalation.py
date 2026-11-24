"""Escalation summary generator for low-confidence diagnostic investigations.

Owner: Person B
Architecture Section 6, Section 7 Rule 6, & Day 5 Task B3:
- Summarizes top-3 root cause hypotheses ranked by confidence
- Provides direct empirical evidence links with inspection queries
- Formulates actionable suggested next steps for the on-call engineer
- Enables an engineer to act immediately without re-investigating from scratch
- Renders to structured Markdown and Slack Block Kit
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from contracts.models import Evidence, Hypothesis

logger = logging.getLogger("reporter.escalation")


@dataclass
class EvidenceLink:
    """An empirical evidence citation linked with exact query or inspection command."""
    id: str
    type: str  # log, metric, commit, config, past_incident
    ref: str
    excerpt: str
    ts: str = ""
    query_or_url: str = ""

    @classmethod
    def from_evidence(cls, ev: Evidence, service: str = "orders") -> EvidenceLink:
        """Construct EvidenceLink from a contract Evidence model with direct inspect query."""
        ev_type = ev.type.lower()
        query_or_url = ""

        if ev_type == "log":
            query_or_url = f"GET /logs/query?service={service}&level=ERROR"
        elif ev_type == "metric":
            query_or_url = f"GET /metrics/query?metric_name={ev.ref}"
        elif ev_type == "commit":
            query_or_url = f"git show {ev.ref}"
        elif ev_type == "config":
            query_or_url = f"GET /changes?service={service}&type=config"
        elif ev_type == "past_incident":
            query_or_url = f"search_past_incidents(incident_id='{ev.ref}')"

        return cls(
            id=ev.id,
            type=ev.type.upper(),
            ref=ev.ref,
            excerpt=ev.excerpt,
            ts=ev.ts,
            query_or_url=query_or_url,
        )


@dataclass
class HypothesisSummary:
    """Summary of a single root-cause hypothesis."""
    rank: int
    cause: str
    category: str
    confidence: float
    evidence_ids: List[str] = field(default_factory=list)
    culprit_change: Optional[str] = None


@dataclass
class EscalationSummary:
    """Structured escalation report for low-confidence incident investigations."""
    incident_id: str
    service: str
    escalation_reason: str
    hypotheses: List[HypothesisSummary]
    evidence_links: List[EvidenceLink]
    suggested_next_steps: List[str]
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_markdown(self) -> str:
        """Render comprehensive, actionable incident briefing as Markdown."""
        lines = [
            f"# :rotating_light: Incident Escalation Summary: `{self.incident_id}`",
            "",
            f"**Target Service:** `{self.service}` | **Status:** `ESCALATED`",
            f"**Escalation Reason:** {self.escalation_reason}",
            "",
            "---",
            "",
            "## :mag: Top Root Cause Hypotheses",
            "",
        ]

        if not self.hypotheses:
            lines.append("_No hypotheses formulated prior to escalation._")
        else:
            for h in self.hypotheses:
                citations = " ".join(f"`[{eid}]`" for eid in h.evidence_ids) if h.evidence_ids else "`[GUESS]`"
                culprit = f" (Culprit: `{h.culprit_change}`)" if h.culprit_change else ""
                lines.append(
                    f"### {h.rank}. [{h.category.upper()}] Confidence: {h.confidence:.0%} {citations}{culprit}"
                )
                lines.append(f"> {h.cause}")
                lines.append("")

        lines.extend([
            "---",
            "",
            "## :link: Empirical Evidence Links",
            "",
        ])

        if not self.evidence_links:
            lines.append("_No empirical evidence citations available._")
        else:
            for ev in self.evidence_links:
                lines.append(f"- **`[{ev.id}]` {ev.type}** `{ev.ref}`")
                lines.append(f"  - *Excerpt:* `{ev.excerpt}`")
                if ev.query_or_url:
                    lines.append(f"  - *Inspect Command:* `{ev.query_or_url}`")
            lines.append("")

        lines.extend([
            "---",
            "",
            "## :clipboard: Suggested Next Steps for On-Call Engineer",
            "",
        ])

        if not self.suggested_next_steps:
            lines.append("1. Manually inspect active pod logs and Prometheus error rates.")
            lines.append("2. Assess recent deployments and trigger manual rollback if degraded.")
        else:
            for i, step in enumerate(self.suggested_next_steps, 1):
                lines.append(f"{i}. {step}")

        return "\n".join(lines)

    def to_slack_blocks(self) -> List[Dict[str, Any]]:
        """Render Block Kit blocks for dispatch via SlackReporter."""
        blocks: List[Dict[str, Any]] = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Escalation Briefing: {self.incident_id}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Service:*\n`{self.service}`"},
                    {"type": "mrkdwn", "text": "*Status:*\n`ESCALATED`"},
                    {"type": "mrkdwn", "text": f"*Reason:*\n{self.escalation_reason}"},
                ],
            },
        ]

        # Top Hypotheses section
        if self.hypotheses:
            hypo_lines = []
            for h in self.hypotheses:
                cites = " ".join(f"`[{eid}]`" for eid in h.evidence_ids) if h.evidence_ids else "`[GUESS]`"
                culprit = f" (`{h.culprit_change}`)" if h.culprit_change else ""
                hypo_lines.append(
                    f"*{h.rank}. [{h.category.upper()}] {h.confidence:.0%}* {cites}{culprit}\n>{h.cause}"
                )
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Top Hypotheses:*\n" + "\n\n".join(hypo_lines)},
            })

        # Evidence links
        if self.evidence_links:
            ev_lines = []
            for ev in self.evidence_links[:4]:
                inspect = f" | `{ev.query_or_url}`" if ev.query_or_url else ""
                ev_lines.append(f"• `[{ev.id}]` *{ev.type}* `{ev.ref}`: _{ev.excerpt[:80]}_{inspect}")
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Evidence Citations:*\n" + "\n".join(ev_lines)},
            })

        # Next Steps
        if self.suggested_next_steps:
            steps_text = "\n".join(f"*{i}.* {s}" for i, s in enumerate(self.suggested_next_steps, 1))
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Actionable Next Steps:*\n" + steps_text},
            })

        return blocks


class EscalationGenerator:
    """Constructs complete, human-actionable escalation summaries from agent outputs."""

    DEFAULT_CONFIDENCE_THRESHOLD = 0.60

    @classmethod
    def generate_summary(
        cls,
        incident_id: str,
        service: str,
        hypotheses: Sequence[Hypothesis],
        evidence: Sequence[Evidence],
        escalation_reason: Optional[str] = None,
        suggested_next_steps: Optional[Sequence[str]] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> EscalationSummary:
        """Build an EscalationSummary with ranked top-3 hypotheses, evidence links, and actionable next steps."""
        # 1. Sort hypotheses by confidence descending and select up to top 3
        sorted_hypotheses = sorted(hypotheses, key=lambda h: h.confidence, reverse=True)[:3]
        top_hypo_summaries: list[HypothesisSummary] = []
        for rank, h in enumerate(sorted_hypotheses, 1):
            top_hypo_summaries.append(
                HypothesisSummary(
                    rank=rank,
                    cause=h.cause,
                    category=h.category,
                    confidence=h.confidence,
                    evidence_ids=list(h.evidence_ids),
                    culprit_change=h.culprit_change,
                )
            )

        # 2. Map evidence links
        evidence_dict = {ev.id: ev for ev in evidence}
        # Gather all evidence IDs cited in top hypotheses first, then remaining evidence
        cited_ids = []
        for h in top_hypo_summaries:
            for eid in h.evidence_ids:
                if eid in evidence_dict and eid not in cited_ids:
                    cited_ids.append(eid)

        all_evidence_links: list[EvidenceLink] = []
        for eid in cited_ids:
            all_evidence_links.append(EvidenceLink.from_evidence(evidence_dict[eid], service=service))

        # Add remaining evidence not cited in top hypotheses
        for ev in evidence:
            if ev.id not in cited_ids:
                all_evidence_links.append(EvidenceLink.from_evidence(ev, service=service))

        # 3. Determine reason
        top_confidence = top_hypo_summaries[0].confidence if top_hypo_summaries else 0.0
        if not escalation_reason:
            escalation_reason = (
                f"Diagnostic confidence is low (top hypothesis confidence {top_confidence:.0%} "
                f"< threshold {confidence_threshold:.0%}); automatic remediation halted to ensure safety."
            )

        # 4. Formulate actionable next steps if not provided
        steps = list(suggested_next_steps or [])
        if not steps:
            steps = cls._synthesize_actionable_next_steps(
                service=service,
                hypotheses=top_hypo_summaries,
                evidence=all_evidence_links,
            )

        return EscalationSummary(
            incident_id=incident_id,
            service=service,
            escalation_reason=escalation_reason,
            hypotheses=top_hypo_summaries,
            evidence_links=all_evidence_links,
            suggested_next_steps=steps,
        )

    @classmethod
    def _synthesize_actionable_next_steps(
        cls,
        service: str,
        hypotheses: Sequence[HypothesisSummary],
        evidence: Sequence[EvidenceLink],
    ) -> List[str]:
        """Synthesize concrete next steps based on category, culprit, and evidence."""
        steps: list[str] = []

        if not hypotheses:
            return [
                f"Inspect live application logs: `GET /logs/query?service={service}&level=ERROR`",
                f"Review recent change events: `GET /changes?service={service}`",
                "Verify system health and downstream dependencies.",
            ]

        top_h = hypotheses[0]
        cat = top_h.category.lower()

        # Step 1: Target investigation of primary culprit / hypothesis
        if top_h.culprit_change:
            steps.append(
                f"Inspect suspected culprit change `{top_h.culprit_change}` with `git show {top_h.culprit_change}`."
            )
        elif cat == "code":
            steps.append(
                f"Examine error stack traces in `{service}` service logs: `GET /logs/query?service={service}&level=ERROR`."
            )
        elif cat == "config":
            steps.append(
                f"Audit recent configuration changes and environment variables for service `{service}`."
            )
        elif cat == "resource":
            steps.append(
                f"Inspect host memory, CPU, and connection pool metrics: `GET /metrics/query?service={service}`."
            )
        elif cat in ("cross_service", "dependency"):
            steps.append(
                f"Trace upstream/downstream dependency latency and error rates for service `{service}`."
            )
        else:
            steps.append(f"Inspect live logs and metrics for service `{service}`.")

        # Step 2: Corroboration with secondary hypothesis
        if len(hypotheses) > 1:
            second_h = hypotheses[1]
            steps.append(
                f"Check alternative hypothesis #{second_h.rank} ({second_h.category}): {second_h.cause[:90]}..."
            )

        # Step 3: Immediate mitigation recommendation
        if top_h.culprit_change:
            steps.append(
                f"If confirmed, execute emergency rollback of `{top_h.culprit_change}` using `/rollback` endpoint."
            )
        else:
            steps.append(
                f"If symptoms persist, isolate `{service}` traffic or scale service replicas to mitigate user impact."
            )

        return steps
