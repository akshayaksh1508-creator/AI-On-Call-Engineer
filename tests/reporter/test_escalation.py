"""Tests for EscalationSummary and EscalationGenerator (Day 5 Task B3).

Owner: Person B
Testing criteria:
1. 5 low-confidence cases each produce a summary a human can act on without re-investigating.
2. Top-3 hypotheses are ranked in descending order of confidence.
3. Evidence links provide direct inspection queries or commands.
4. Concrete, actionable next steps are formulated.
5. Markdown and Slack Block Kit outputs render cleanly.
"""

import unittest

from contracts.models import Evidence, Hypothesis
from reporter.escalation import EscalationGenerator, EscalationSummary
from reporter.slack import SlackReporter


class TestEscalationSummaryCases(unittest.TestCase):
    """5 low-confidence incident scenarios verifying that an on-call engineer can act without re-investigating."""

    def setUp(self):
        self.slack_reporter = SlackReporter(mock=True)

    def test_case_01_cross_service_latency_degradation(self):
        """Case 1: Gateway 504 caused by upstream payments latency spike (conf 0.48)."""
        hypotheses = [
            Hypothesis(
                cause="Upstream payments service /process p99 latency spiked to 4.8s, causing gateway checkout timeouts",
                category="cross_service",
                confidence=0.48,
                evidence_ids=["ev_log_504", "ev_met_lat"],
                culprit_change="dep_payments_v2.4.0",
            ),
            Hypothesis(
                cause="Orders service database connection pool exhausted waiting on slow queries",
                category="resource",
                confidence=0.32,
                evidence_ids=["ev_log_pool"],
            ),
            Hypothesis(
                cause="Network packet loss on ingress load balancer",
                category="dependency",
                confidence=0.15,
                evidence_ids=[],
            ),
        ]
        evidence = [
            Evidence(
                id="ev_log_504",
                type="log",
                ref="gateway/proxy.py:88",
                excerpt="HTTP 504 Gateway Timeout while awaiting response from http://payments:8082/process",
                ts="2026-11-24T06:10:00Z",
            ),
            Evidence(
                id="ev_met_lat",
                type="metric",
                ref="http_request_duration_seconds{service='payments'}",
                excerpt="p99 jumped from 45ms to 4820ms at 06:08:30Z",
                ts="2026-11-24T06:09:00Z",
            ),
            Evidence(
                id="ev_log_pool",
                type="log",
                ref="orders/db.py:34",
                excerpt="DB connection wait queue > 50 threads",
                ts="2026-11-24T06:10:15Z",
            ),
        ]

        summary = EscalationGenerator.generate_summary(
            incident_id="inc-cross-service-01",
            service="gateway",
            hypotheses=hypotheses,
            evidence=evidence,
        )

        self._assert_actionable_escalation_summary(summary, expected_top_conf=0.48)
        self.assertIn("dep_payments_v2.4.0", summary.to_markdown())
        self.assertIn("GET /logs/query?service=gateway&level=ERROR", summary.to_markdown())

    def test_case_02_intermittent_race_condition(self):
        """Case 2: Intermittent concurrency failure in inventory reservation (conf 0.50)."""
        hypotheses = [
            Hypothesis(
                cause="Race condition in inventory reservation dictionary missing lock synchronization under concurrency",
                category="code",
                confidence=0.50,
                evidence_ids=["ev_log_race", "ev_commit_opt"],
                culprit_change="commit_d3f4a1b",
            ),
            Hypothesis(
                cause="Duplicate transaction ID collisions in payment idempotency cache",
                category="code",
                confidence=0.30,
                evidence_ids=["ev_log_dup"],
            ),
            Hypothesis(
                cause="Redis connection timeout under high load spike",
                category="dependency",
                confidence=0.18,
                evidence_ids=[],
            ),
        ]
        evidence = [
            Evidence(
                id="ev_log_race",
                type="log",
                ref="inventory/reservation.py:42",
                excerpt="KeyError: 'item_stock_982' during concurrent decrement_stock",
                ts="2026-11-24T06:15:22Z",
            ),
            Evidence(
                id="ev_commit_opt",
                type="commit",
                ref="commit_d3f4a1b",
                excerpt="perf(inventory): remove mutex lock to optimize reservation throughput",
                ts="2026-11-24T05:50:00Z",
            ),
            Evidence(
                id="ev_log_dup",
                type="log",
                ref="payments/idempotency.py:19",
                excerpt="Warning: key collision detected in in-memory LRU cache",
                ts="2026-11-24T06:16:00Z",
            ),
        ]

        summary = EscalationGenerator.generate_summary(
            incident_id="inc-race-02",
            service="inventory",
            hypotheses=hypotheses,
            evidence=evidence,
        )

        self._assert_actionable_escalation_summary(summary, expected_top_conf=0.50)
        self.assertIn("commit_d3f4a1b", summary.to_markdown())
        self.assertIn("git show commit_d3f4a1b", summary.to_markdown())

    def test_case_03_resource_exhaustion_memory_leak(self):
        """Case 3: Memory leak / unbounded heap growth in orders service (conf 0.45)."""
        hypotheses = [
            Hypothesis(
                cause="Unclosed aiohttp ClientSession instances leaking TCP sockets and heap buffers in order_client.py",
                category="resource",
                confidence=0.45,
                evidence_ids=["ev_met_mem", "ev_log_socket"],
                culprit_change="dep_orders_v1.3.1",
            ),
            Hypothesis(
                cause="In-memory cache LRU eviction disabled in application configuration",
                category="config",
                confidence=0.35,
                evidence_ids=["ev_cfg_cache"],
            ),
            Hypothesis(
                cause="PostgreSQL query buffer bloat on unfiltered historical order queries",
                category="code",
                confidence=0.15,
                evidence_ids=[],
            ),
        ]
        evidence = [
            Evidence(
                id="ev_met_mem",
                type="metric",
                ref="container_memory_working_set_bytes{service='orders'}",
                excerpt="Heap growth rate 25MB/min steadily over 90 minutes; reached 94% cgroup limit",
                ts="2026-11-24T06:20:00Z",
            ),
            Evidence(
                id="ev_log_socket",
                type="log",
                ref="orders/client.py:65",
                excerpt="ResourceWarning: unclosed client session <aiohttp.client.ClientSession>",
                ts="2026-11-24T06:21:00Z",
            ),
            Evidence(
                id="ev_cfg_cache",
                type="config",
                ref="CACHE_MAX_ENTRIES",
                excerpt="CACHE_MAX_ENTRIES was set to 0 (unlimited)",
                ts="2026-11-24T05:30:00Z",
            ),
        ]

        summary = EscalationGenerator.generate_summary(
            incident_id="inc-mem-03",
            service="orders",
            hypotheses=hypotheses,
            evidence=evidence,
        )

        self._assert_actionable_escalation_summary(summary, expected_top_conf=0.45)
        self.assertIn("container_memory_working_set_bytes", summary.to_markdown())
        self.assertIn("dep_orders_v1.3.1", summary.to_markdown())

    def test_case_04_config_drift_auth_token_rotation(self):
        """Case 4: Environment variable / secret rotation mismatch causing 401s (conf 0.42)."""
        hypotheses = [
            Hypothesis(
                cause="JWT signature validation secret rotated in Vault but not refreshed in gateway service container",
                category="config",
                confidence=0.42,
                evidence_ids=["ev_log_401", "ev_cfg_vault"],
                culprit_change="rev_vault_sec_88",
            ),
            Hypothesis(
                cause="Clock drift between container nodes causing token not-yet-valid / expired validation failures",
                category="dependency",
                confidence=0.38,
                evidence_ids=["ev_met_ntp"],
            ),
            Hypothesis(
                cause="Partner integration sending malformed Authorization header prefix",
                category="code",
                confidence=0.18,
                evidence_ids=[],
            ),
        ]
        evidence = [
            Evidence(
                id="ev_log_401",
                type="log",
                ref="gateway/auth.py:55",
                excerpt="jwt.exceptions.InvalidSignatureError: Signature verification failed for iss='auth.internal'",
                ts="2026-11-24T06:25:00Z",
            ),
            Evidence(
                id="ev_cfg_vault",
                type="config",
                ref="VAULT_SECRET_VERSION",
                excerpt="Vault key rotated from v3 to v4 at 06:20:00Z without container reload",
                ts="2026-11-24T06:20:00Z",
            ),
            Evidence(
                id="ev_met_ntp",
                type="metric",
                ref="node_timex_offset_seconds",
                excerpt="Host node offset is 142ms relative to NTP source",
                ts="2026-11-24T06:24:00Z",
            ),
        ]

        summary = EscalationGenerator.generate_summary(
            incident_id="inc-auth-04",
            service="gateway",
            hypotheses=hypotheses,
            evidence=evidence,
        )

        self._assert_actionable_escalation_summary(summary, expected_top_conf=0.42)
        self.assertIn("rev_vault_sec_88", summary.to_markdown())
        self.assertIn("GET /changes?service=gateway&type=config", summary.to_markdown())

    def test_case_05_database_lock_contention(self):
        """Case 5: Long-running analytical query blocking write transactions on orders DB (conf 0.52)."""
        hypotheses = [
            Hypothesis(
                cause="Analytical report query holding AccessExclusiveLock on orders table, blocking API insert transactions",
                category="cross_service",
                confidence=0.52,
                evidence_ids=["ev_met_db_wait", "ev_log_lock"],
                culprit_change="job_daily_analytics_0600",
            ),
            Hypothesis(
                cause="Missing index on customer_id causing table sequential scans on every order lookup",
                category="code",
                confidence=0.28,
                evidence_ids=["ev_log_seqscan"],
            ),
            Hypothesis(
                cause="EBS storage volume I/O throttling on WAL write throughput",
                category="resource",
                confidence=0.18,
                evidence_ids=[],
            ),
        ]
        evidence = [
            Evidence(
                id="ev_met_db_wait",
                type="metric",
                ref="postgresql_locks_waiting_total",
                excerpt="18 write queries blocked waiting on relation 'orders' lock id 16428",
                ts="2026-11-24T06:30:00Z",
            ),
            Evidence(
                id="ev_log_lock",
                type="log",
                ref="orders_db/postgresql.log",
                excerpt="LOG: process 4821 still waiting for ExclusiveLock on relation orders after 12000.12ms",
                ts="2026-11-24T06:30:15Z",
            ),
            Evidence(
                id="ev_log_seqscan",
                type="log",
                ref="orders_db/postgresql.log",
                excerpt="QUERY PLAN: Seq Scan on orders (cost=0.00..8450.20 rows=280000 width=128)",
                ts="2026-11-24T06:29:00Z",
            ),
        ]

        summary = EscalationGenerator.generate_summary(
            incident_id="inc-db-05",
            service="orders_db",
            hypotheses=hypotheses,
            evidence=evidence,
        )

        self._assert_actionable_escalation_summary(summary, expected_top_conf=0.52)
        self.assertIn("job_daily_analytics_0600", summary.to_markdown())
        self.assertIn("postgresql_locks_waiting_total", summary.to_markdown())

    def _assert_actionable_escalation_summary(self, summary: EscalationSummary, expected_top_conf: float):
        """Verify the escalation summary provides full actionability for an engineer without re-investigating."""
        # 1. Hypotheses: exactly top-3 (or fewer if fewer provided), ranked in strict descending confidence
        self.assertLessEqual(len(summary.hypotheses), 3)
        self.assertGreaterEqual(len(summary.hypotheses), 1)

        confidences = [h.confidence for h in summary.hypotheses]
        self.assertEqual(confidences, sorted(confidences, reverse=True), "Hypotheses must be ranked by confidence")
        self.assertAlmostEqual(summary.hypotheses[0].confidence, expected_top_conf, places=2)
        self.assertLess(summary.hypotheses[0].confidence, 0.60, "Top-1 confidence must be under 0.60 threshold")

        # 2. Evidence Links: cited evidence is mapped with inspection queries
        self.assertGreater(len(summary.evidence_links), 0)
        for ev_link in summary.evidence_links:
            self.assertTrue(ev_link.id.startswith("ev_"))
            self.assertTrue(bool(ev_link.excerpt))
            self.assertTrue(bool(ev_link.query_or_url), f"Evidence {ev_link.id} must have direct inspect command")

        # 3. Actionable next steps: at least 2 concrete steps provided
        self.assertGreaterEqual(len(summary.suggested_next_steps), 2)
        for step in summary.suggested_next_steps:
            self.assertGreater(len(step), 15, "Next steps must be descriptive and concrete")

        # 4. Markdown format contains all key sections
        md = summary.to_markdown()
        self.assertIn(summary.incident_id, md)
        self.assertIn("Top Root Cause Hypotheses", md)
        self.assertIn("Empirical Evidence Links", md)
        self.assertIn("Suggested Next Steps", md)

        # 5. Slack Block Kit payload formats validly and dispatches via SlackReporter
        blocks = summary.to_slack_blocks()
        self.assertIsInstance(blocks, list)
        self.assertGreaterEqual(len(blocks), 3)

        # Dispatch via mock Slack reporter
        res = self.slack_reporter.send_message(text=f"Escalation for {summary.incident_id}", blocks=blocks)
        self.assertTrue(res.get("ok"))


class TestEscalationRankingAndLimits(unittest.TestCase):
    """Verify hypothesis truncation and sorting logic."""

    def test_hypotheses_truncated_to_top_three(self):
        """When 5 hypotheses are provided, only the top 3 with highest confidence are included."""
        hypos = [
            Hypothesis(cause="Cause E", category="code", confidence=0.10),
            Hypothesis(cause="Cause B", category="code", confidence=0.45),
            Hypothesis(cause="Cause D", category="code", confidence=0.20),
            Hypothesis(cause="Cause A", category="code", confidence=0.55),
            Hypothesis(cause="Cause C", category="code", confidence=0.35),
        ]
        summary = EscalationGenerator.generate_summary(
            incident_id="inc-trunc",
            service="orders",
            hypotheses=hypos,
            evidence=[],
        )

        self.assertEqual(len(summary.hypotheses), 3)
        self.assertEqual(summary.hypotheses[0].cause, "Cause A")
        self.assertEqual(summary.hypotheses[0].confidence, 0.55)
        self.assertEqual(summary.hypotheses[1].cause, "Cause B")
        self.assertEqual(summary.hypotheses[1].confidence, 0.45)
        self.assertEqual(summary.hypotheses[2].cause, "Cause C")
        self.assertEqual(summary.hypotheses[2].confidence, 0.35)


if __name__ == "__main__":
    unittest.main()
