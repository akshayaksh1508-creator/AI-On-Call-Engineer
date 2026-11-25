"""Final Slack & GitHub PR Recovery Report (Day 7 Task B4).

Generates and publishes the complete 6-part incident resolution report to both
Slack and GitHub PR, including an SVG recovery graph with fault and fix markers.

Owner: Person B (Brain & Trust)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from contracts.models import Evidence, FixProposal, Hypothesis, Incident, VerificationResult
from reporter.github_pr import GitHubPRClient
from reporter.postmortem import PostmortemGenerator, PostmortemReport
from reporter.slack import SlackReporter


def generate_recovery_graph_svg(
    *,
    incident_id: str,
    service: str,
    metric_before: float,
    metric_after: float,
    out_path: Union[str, Path],
) -> Path:
    """Render an SVG time-series recovery graph with fault injection and fix markers."""
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    width, height = 760, 320
    pad_l, pad_r, pad_t, pad_b = 70, 40, 56, 54
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    peak = max(metric_before, metric_after, 0.05) * 1.15
    # 7 synthetic timeline points showing: baseline -> fault spike -> fix -> recovery
    series = [
        ("t-60s", 0.002),
        ("t-40s", metric_before * 0.85),
        ("t-20s", metric_before),
        ("t=0s (Fix)", metric_before),
        ("t+15s", (metric_before + metric_after) * 0.35),
        ("t+30s", metric_after),
        ("t+60s", metric_after),
    ]

    coords: List[tuple[float, float, str, float]] = []
    for idx, (lbl, val) in enumerate(series):
        x = pad_l + (idx / (len(series) - 1)) * plot_w
        y = pad_t + plot_h - min(1.0, max(0.0, val / peak)) * plot_h
        coords.append((x, y, lbl, val))

    polyline_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in coords)
    fault_x, fault_y = coords[1][0], coords[1][1]
    fix_x, fix_y = coords[3][0], coords[3][1]
    rec_x, rec_y = coords[5][0], coords[5][1]

    x_labels = "".join(
        f'<text x="{x:.1f}" y="{height - 20}" fill="#8b949e" '
        f'font-family="Consolas, monospace" font-size="11" text-anchor="middle">{lbl}</text>'
        for x, _, lbl, _ in coords
    )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" rx="8" fill="#0d1117"/>'
        f'<text x="24" y="34" fill="#58a6ff" font-family="Segoe UI, Arial, sans-serif" '
        f'font-size="16" font-weight="bold">'
        f'NightShift Recovery Graph — {service} ({incident_id})</text>'
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" stroke="#30363d" stroke-width="1"/>'
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" stroke="#30363d" stroke-width="1"/>'
        f'<polyline fill="none" stroke="#58a6ff" stroke-width="3" points="{polyline_pts}"/>'
        f'<circle cx="{fault_x:.1f}" cy="{fault_y:.1f}" r="5" fill="#f85149"/>'
        f'<text x="{fault_x:.1f}" y="{fault_y - 10:.1f}" fill="#f85149" font-size="11" text-anchor="middle">Fault ({metric_before:.1%})</text>'
        f'<line x1="{fix_x:.1f}" y1="{pad_t}" x2="{fix_x:.1f}" y2="{pad_t + plot_h}" stroke="#d29922" stroke-dasharray="4,4" stroke-width="1.5"/>'
        f'<circle cx="{fix_x:.1f}" cy="{fix_y:.1f}" r="5" fill="#d29922"/>'
        f'<text x="{fix_x:.1f}" y="{pad_t + 14}" fill="#d29922" font-size="11" text-anchor="middle">Fix Applied</text>'
        f'<circle cx="{rec_x:.1f}" cy="{rec_y:.1f}" r="5" fill="#3fb950"/>'
        f'<text x="{rec_x:.1f}" y="{rec_y - 10:.1f}" fill="#3fb950" font-size="11" text-anchor="middle">Recovered ({metric_after:.2%})</text>'
        f'{x_labels}'
        f'</svg>'
    )
    target.write_text(svg, encoding="utf-8")
    return target


@dataclass
class FinalReportResult:
    """Published final report artifacts, links, and delivery responses."""

    incident_id: str
    fault_id: str
    postmortem: PostmortemReport
    postmortem_path: Path
    recovery_graph_path: Path
    pr_url: str
    pr_number: int
    slack_response: Dict[str, Any]
    pr_comment_response: Dict[str, Any]
    markdown_report: str
    slack_text: str
    links: Dict[str, str] = field(default_factory=dict)
    sections_present: List[str] = field(default_factory=list)


class FinalReportPublisher:
    """Generates and publishes the 6-part final report with recovery graph to Slack and PR."""

    def __init__(self, postmortem_generator: Optional[PostmortemGenerator] = None) -> None:
        self.postmortem_generator = postmortem_generator or PostmortemGenerator()

    def publish(
        self,
        *,
        incident: Incident,
        fault_id: str,
        hypothesis: Hypothesis,
        proposal: FixProposal,
        verification: VerificationResult,
        slack_reporter: SlackReporter,
        pr_client: GitHubPRClient,
        out_dir: Union[str, Path],
        evidence_items: Optional[Sequence[Union[Evidence, Dict[str, Any]]]] = None,
        transitions: Optional[Sequence[Any]] = None,
        head_branch: Optional[str] = None,
    ) -> FinalReportResult:
        out_root = Path(out_dir)
        out_root.mkdir(parents=True, exist_ok=True)

        # 1. Open/update PR first so pr_url & pr_number resolve cleanly
        branch = head_branch or f"fix-{incident.id}"
        pr_data = pr_client.create_remediation_pr(
            incident=incident,
            hypothesis=hypothesis,
            proposal=proposal,
            verification=verification,
            head_branch=branch,
        )
        pr_number = int(pr_data["number"])
        pr_url = str(pr_data["html_url"])

        # 2. Generate Recovery Graph SVG
        graph_path = generate_recovery_graph_svg(
            incident_id=incident.id,
            service=incident.service,
            metric_before=verification.metric_before,
            metric_after=verification.metric_after,
            out_path=out_root / f"recovery_graph_{incident.id}.svg",
        )

        # 3. Generate & Save 6-part Postmortem
        pm = self.postmortem_generator.generate(
            incident,
            fault_id=fault_id,
            hypothesis=hypothesis,
            proposal=proposal,
            verification=verification,
            evidence_items=evidence_items,
            transitions=transitions,
            pr_url=pr_url,
        )
        pm_path = self.postmortem_generator.save_markdown(
            pm,
            out_root / f"postmortem_{incident.id}.md",
        )

        graph_uri = graph_path.resolve().as_uri()
        pm_uri = pm_path.resolve().as_uri()
        links = {
            "pr_url": pr_url,
            "recovery_graph_path": str(graph_path),
            "recovery_graph_uri": graph_uri,
            "postmortem_path": str(pm_path),
            "postmortem_uri": pm_uri,
        }

        # 4. Format 6-part Markdown Report (for PR comment)
        timeline_lines = "\n".join(
            f"- `{t['timestamp']}` **[{t['stage']}]** {t['event']} (`{t['evidence_id']}`)"
            for t in pm.timeline
        )
        evidence_lines = "\n".join(
            f"- `{e['evidence_id']}` ({e['source']}): {e['summary']}"
            for e in pm.evidence
        )
        followup_lines = "\n".join(
            f"- [{fu['priority']}] {fu['action']} (Owner: `{fu['owner']}`, Evidence: `{fu['evidence_id']}`)"
            for fu in pm.follow_ups
        )

        md_report = (
            f"## NightShift Final Incident & Recovery Report (`{incident.id}`)\n\n"
            f"### 1. Timeline\n{timeline_lines}\n\n"
            f"### 2. Root Cause\n"
            f"- **Cause:** {pm.cause['summary']}\n"
            f"- **Category:** `{pm.cause['category']}` (Confidence: {pm.cause['confidence']:.0%})\n\n"
            f"### 3. Evidence\n{evidence_lines}\n\n"
            f"### 4. Remediation Fix & PR\n"
            f"- **Type / Tier:** `{pm.fix['type']}` (`{pm.fix['risk_tier']}`)\n"
            f"- **Rationale:** {pm.fix['rationale']}\n"
            f"- **Pull Request:** [{pr_url}]({pr_url})\n\n"
            f"### 5. Verification & Recovery Graph\n"
            f"- **Verdict:** **{verification.verdict}**\n"
            f"- **Error Rate:** `{verification.metric_before:.2%}` -> `{verification.metric_after:.2%}`\n"
            f"- **Recovery Graph:** [recovery_graph_{incident.id}.svg]({graph_uri})\n\n"
            f"### 6. Follow-ups & Postmortem\n"
            f"- **Postmortem Document:** [postmortem_{incident.id}.md]({pm_uri})\n"
            f"{followup_lines}\n"
        )

        pr_comment_resp = pr_client.add_comment(pr_number, md_report)

        # 5. Dispatch 6-part Slack Final Report with Block Kit + Recovery Graph link
        slack_text = (
            f":white_check_mark: *[NIGHTSHIFT FINAL REPORT]* `{incident.id}` ({fault_id}) — "
            f"Verdict: *{verification.verdict}* (`{verification.metric_before:.2%}` -> `{verification.metric_after:.2%}`)\n"
            f"1. *Timeline:* {len(pm.timeline)} stages recorded ({pm.timeline[0]['stage']} -> {pm.timeline[-1]['stage']})\n"
            f"2. *Root Cause:* {pm.cause['summary']}\n"
            f"3. *Evidence:* {', '.join(e['evidence_id'] for e in pm.evidence[:4])}\n"
            f"4. *Fix & PR:* `{pm.fix['type']}` (`{pm.fix['risk_tier']}`) — <{pr_url}|PR #{pr_number}>\n"
            f"5. *Verification & Recovery Graph:* {verification.verdict} | <{graph_uri}|Recovery Graph SVG>\n"
            f"6. *Follow-ups & Postmortem:* {len(pm.follow_ups)} action items | <{pm_uri}|Full Postmortem>"
        )
        slack_blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"NightShift Final Report: {incident.id}"},
            },
            {"type": "section", "text": {"type": "mrkdwn", "text": slack_text}},
        ]
        slack_resp = slack_reporter.send_message(slack_text, blocks=slack_blocks)

        return FinalReportResult(
            incident_id=incident.id,
            fault_id=fault_id,
            postmortem=pm,
            postmortem_path=pm_path,
            recovery_graph_path=graph_path,
            pr_url=pr_url,
            pr_number=pr_number,
            slack_response=slack_resp,
            pr_comment_response=pr_comment_resp,
            markdown_report=md_report,
            slack_text=slack_text,
            links=links,
            sections_present=[
                "timeline",
                "cause",
                "evidence",
                "fix",
                "verification_and_recovery_graph",
                "follow_ups_and_postmortem",
            ],
        )
