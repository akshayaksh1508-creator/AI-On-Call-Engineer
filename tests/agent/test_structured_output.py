"""Unit Tests for Structured Output, Evidence ID Generation, and Schema Validation (Day 2 Task B3).

Owner: Person B (Brain & Trust)
Verifies:
1. EvidenceIdGenerator produces collision-free, categorized evidence IDs.
2. Self-healing JSON repair (markdown fences, quotes, Python literals, trailing commas, unclosed brackets).
3. Field normalizers for category, confidence, and evidence type.
4. Strict citation enforcement: uncited claims and unreferenced IDs are flagged.
5. 20 diverse sample runs: 100% schema-valid after at most one repair.
"""

import json
import unittest
from typing import Any, Dict, List

from contracts.models import Evidence, Hypothesis
from agent.structured_output import (
    EvidenceIdGenerator,
    StructuredDiagnosis,
    build_repair_prompt,
    extract_and_parse_json,
    normalize_category,
    normalize_confidence,
    normalize_evidence_type,
    parse_structured_diagnosis,
    repair_json_string,
    validate_and_build_diagnosis,
)


class TestEvidenceIdGenerator(unittest.TestCase):
    """Tests for the EvidenceIdGenerator utility."""

    def setUp(self):
        self.generator = EvidenceIdGenerator()

    def test_01_typed_prefix_generation(self):
        """Generates predictable prefixes matching evidence categories."""
        id_log = self.generator.generate("log")
        id_metric = self.generator.generate("metric")
        id_commit = self.generator.generate("commit")
        id_config = self.generator.generate("config")
        id_past = self.generator.generate("past_incident")

        self.assertEqual(id_log, "ev_log_001")
        self.assertEqual(id_metric, "ev_metric_001")
        self.assertEqual(id_commit, "ev_commit_001")
        self.assertEqual(id_config, "ev_config_001")
        self.assertEqual(id_past, "ev_past_001")

    def test_02_sequential_counters_and_uniqueness(self):
        """Consecutive calls for same type produce sequential, non-colliding IDs."""
        id1 = self.generator.generate("log")
        id2 = self.generator.generate("log")
        id3 = self.generator.generate("log")

        self.assertEqual(id1, "ev_log_001")
        self.assertEqual(id2, "ev_log_002")
        self.assertEqual(id3, "ev_log_003")
        self.assertTrue(self.generator.is_registered("ev_log_003"))

    def test_03_registration_prevents_collision(self):
        """Pre-registering an existing ID causes generator to increment past it."""
        self.generator.register("ev_log_005")
        next_id = self.generator.generate("log")
        self.assertEqual(next_id, "ev_log_006")

    def test_04_reset_clears_state(self):
        """Reset clears registered IDs and resets counters."""
        self.generator.generate("log")
        self.generator.reset()
        self.assertEqual(len(self.generator.get_registered_ids()), 0)
        self.assertEqual(self.generator.generate("log"), "ev_log_001")


class TestJSONRepairAndNormalization(unittest.TestCase):
    """Tests for deterministic JSON repair and normalizer functions."""

    def test_01_repair_markdown_fences(self):
        """Strips markdown code blocks."""
        raw = "```json\n{\"cause\": \"syntax error\", \"confidence\": 0.9}\n```"
        repaired = repair_json_string(raw)
        data = json.loads(repaired)
        self.assertEqual(data["cause"], "syntax error")

    def test_02_repair_single_quotes(self):
        """Converts single quotes to double quotes for valid JSON."""
        raw = "{'cause': 'bad config', 'confidence': 0.85}"
        repaired = repair_json_string(raw)
        data = json.loads(repaired)
        self.assertEqual(data["cause"], "bad config")
        self.assertEqual(data["confidence"], 0.85)

    def test_03_repair_python_constants(self):
        """Replaces True, False, None with true, false, null."""
        raw = '{"verified": True, "active": False, "reason": None}'
        repaired = repair_json_string(raw)
        data = json.loads(repaired)
        self.assertIs(data["verified"], True)
        self.assertIs(data["active"], False)
        self.assertIsNone(data["reason"])

    def test_04_repair_trailing_commas(self):
        """Removes trailing commas inside objects and arrays."""
        raw = '{"items": ["a", "b",], "nested": {"k": 1,},}'
        repaired = repair_json_string(raw)
        data = json.loads(repaired)
        self.assertEqual(data["items"], ["a", "b"])
        self.assertEqual(data["nested"]["k"], 1)

    def test_05_repair_unclosed_brackets_truncation(self):
        """Balances unclosed brackets when JSON is truncated."""
        raw = '{"hypotheses": [{"cause": "OOM", "confidence": 0.9'
        repaired = repair_json_string(raw)
        data = json.loads(repaired)
        self.assertEqual(data["hypotheses"][0]["cause"], "OOM")

    def test_06_normalize_categories(self):
        """Maps various aliases to canonical category literals."""
        self.assertEqual(normalize_category("cross-service"), "cross_service")
        self.assertEqual(normalize_category("cross service"), "cross_service")
        self.assertEqual(normalize_category("upstream"), "cross_service")
        self.assertEqual(normalize_category("oom"), "resource")
        self.assertEqual(normalize_category("memory"), "resource")
        self.assertEqual(normalize_category("bug"), "code")
        self.assertEqual(normalize_category("env"), "config")
        self.assertEqual(normalize_category("database"), "dependency")
        self.assertEqual(normalize_category("random_val"), "unknown")

    def test_07_normalize_confidence(self):
        """Normalizes floats, percentages, strings, and bounds values to [0.0, 1.0]."""
        self.assertEqual(normalize_confidence(0.95), 0.95)
        self.assertEqual(normalize_confidence(95), 0.95)
        self.assertEqual(normalize_confidence("85%"), 0.85)
        self.assertEqual(normalize_confidence("high"), 0.9)
        self.assertEqual(normalize_confidence(1.5), 1.0)
        self.assertEqual(normalize_confidence(-0.5), 0.0)

    def test_08_normalize_evidence_types(self):
        """Maps aliases to canonical evidence type literals."""
        self.assertEqual(normalize_evidence_type("logs"), "log")
        self.assertEqual(normalize_evidence_type("telemetry"), "metric")
        self.assertEqual(normalize_evidence_type("git"), "commit")
        self.assertEqual(normalize_evidence_type("env"), "config")
        self.assertEqual(normalize_evidence_type("history"), "past_incident")


class TestStructuredDiagnosisValidation(unittest.TestCase):
    """Tests for schema validation, citation tracking, and repair prompts."""

    def test_01_valid_diagnosis_end_to_end(self):
        """Parses and validates a fully formed diagnosis."""
        raw = {
            "investigation_summary": "Gateway 502 caused by orders service exception.",
            "evidence": [
                {
                    "id": "ev_log_001",
                    "type": "log",
                    "ref": "target-app/orders/main.py:45",
                    "excerpt": "KeyError: 'customer_id'",
                    "ts": "2026-11-23T10:00:00Z",
                }
            ],
            "hypotheses": [
                {
                    "cause": "Missing key in orders request payload [ev_log_001]",
                    "category": "code",
                    "confidence": 0.92,
                    "evidence_ids": ["ev_log_001"],
                    "culprit_change": "git_sha_abc123",
                }
            ],
            "uncited_claims": [],
            "recommended_action": "propose_fix",
        }
        diagnosis = validate_and_build_diagnosis(raw)

        self.assertIsInstance(diagnosis, StructuredDiagnosis)
        self.assertEqual(len(diagnosis.hypotheses), 1)
        self.assertIsInstance(diagnosis.hypotheses[0], Hypothesis)
        self.assertEqual(len(diagnosis.evidence), 1)
        self.assertIsInstance(diagnosis.evidence[0], Evidence)
        self.assertEqual(len(diagnosis.uncited_claims), 0)

    def test_02_uncited_hypothesis_flagged_as_guess(self):
        """Hypothesis with no evidence IDs is explicitly flagged as a [GUESS]."""
        raw = {
            "hypotheses": [
                {
                    "cause": "Maybe database connection pool is full",
                    "category": "resource",
                    "confidence": 0.40,
                    "evidence_ids": [],
                }
            ]
        }
        diagnosis = validate_and_build_diagnosis(raw)
        self.assertTrue(any("[GUESS]" in uc for uc in diagnosis.uncited_claims))

    def test_03_unreferenced_evidence_id_flagged(self):
        """Hypothesis citing an ID not in the evidence list is flagged as [UNREFERENCED]."""
        raw = {
            "evidence": [
                {
                    "id": "ev_log_001",
                    "type": "log",
                    "ref": "orders.log",
                    "excerpt": "Error 500",
                    "ts": "2026-11-23T10:00:00Z",
                }
            ],
            "hypotheses": [
                {
                    "cause": "Failure in payment gateway",
                    "category": "dependency",
                    "confidence": 0.80,
                    "evidence_ids": ["ev_metric_ghost"],
                }
            ],
        }
        diagnosis = validate_and_build_diagnosis(raw)
        self.assertTrue(any("[UNREFERENCED]" in uc for uc in diagnosis.uncited_claims))

    def test_04_missing_evidence_id_auto_assigned(self):
        """Evidence item without an explicit ID receives an auto-generated ID."""
        raw = {
            "evidence": [
                {
                    "type": "log",
                    "ref": "orders.log",
                    "excerpt": "Exception raised",
                    "ts": "2026-11-23T10:00:00Z",
                }
            ],
            "hypotheses": [],
        }
        diagnosis = validate_and_build_diagnosis(raw)
        self.assertEqual(len(diagnosis.evidence), 1)
        self.assertTrue(diagnosis.evidence[0].id.startswith("ev_log_"))

    def test_05_repair_prompt_structure(self):
        """build_repair_prompt produces formatted guidance and schema."""
        prompt = build_repair_prompt("Invalid JSON", "{bad text")
        self.assertIn("ERROR DETAILS:", prompt)
        self.assertIn("REQUIRED FORMAT:", prompt)
        self.assertIn("MANDATORY RULES:", prompt)


class TestTwentySampleRunsValidation(unittest.TestCase):
    """Day 2 Task B3 Core Acceptance Test: 20 Diverse Sample Runs.

    Requirement: 20 sample runs: 100% schema-valid after at most one repair;
    any claim without an evidence ID is flagged.
    """

    def setUp(self):
        self.samples = self._generate_twenty_diverse_samples()

    def _generate_twenty_diverse_samples(self) -> List[Dict[str, Any]]:
        """Construct 20 realistic, varied LLM output scenarios."""
        return [
            # Sample 1: Perfect, clean JSON with multiple hypotheses
            {
                "id": "sample_01_perfect_json",
                "raw_text": json.dumps({
                    "investigation_summary": "Order service throws 500 on checkout.",
                    "evidence": [
                        {"id": "ev_log_001", "type": "log", "ref": "orders/app.py:100", "excerpt": "ZeroDivisionError", "ts": "2026-11-23T10:05:00Z"},
                        {"id": "ev_metric_001", "type": "metric", "ref": "http_requests_total", "excerpt": "error rate 22%", "ts": "2026-11-23T10:05:10Z"}
                    ],
                    "hypotheses": [
                        {"cause": "Division by zero in pricing formula [ev_log_001]", "category": "code", "confidence": 0.95, "evidence_ids": ["ev_log_001", "ev_metric_001"], "culprit_change": "commit_111"},
                        {"cause": "Gateway timeout [ev_metric_001]", "category": "cross_service", "confidence": 0.20, "evidence_ids": ["ev_metric_001"]}
                    ],
                    "uncited_claims": [],
                    "recommended_action": "propose_fix"
                }),
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 2: Markdown code block wrapped with conversational intro & outro
            {
                "id": "sample_02_markdown_fenced",
                "raw_text": (
                    "Based on my investigation, here is the diagnosis:\n\n"
                    "```json\n"
                    "{\n"
                    '  "investigation_summary": "Found database authentication failure.",\n'
                    '  "evidence": [{"id": "ev_log_002", "type": "log", "ref": "auth.py:20", "excerpt": "FATAL: password authentication failed", "ts": "2026-11-23T10:01:00Z"}],\n'
                    '  "hypotheses": [{"cause": "DB password rotation mismatch [ev_log_002]", "category": "config", "confidence": 0.90, "evidence_ids": ["ev_log_002"], "culprit_change": "cfg_rev_4"}],\n'
                    '  "recommended_action": "propose_fix"\n'
                    "}\n"
                    "```\n"
                    "I recommend reverting the config revision."
                ),
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 3: Trailing commas in arrays and objects
            {
                "id": "sample_03_trailing_commas",
                "raw_text": """{
                    "investigation_summary": "Config parameter typo in payments.",
                    "evidence": [
                        {"id": "ev_config_001", "type": "config", "ref": "payments.env", "excerpt": "STRIPE_URL=null", "ts": "2026-11-23T10:02:00Z",},
                    ],
                    "hypotheses": [
                        {"cause": "Stripe endpoint set to null [ev_config_001]", "category": "config", "confidence": 0.93, "evidence_ids": ["ev_config_001"], "culprit_change": "env_rev_2",},
                    ],
                    "recommended_action": "propose_fix",
                }""",
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 4: Python single quotes and None literal
            {
                "id": "sample_04_single_quotes_and_python_literals",
                "raw_text": """{
                    'investigation_summary': 'Upstream inventory service down.',
                    'evidence': [
                        {'id': 'ev_log_004', 'type': 'log', 'ref': 'inventory/log', 'excerpt': 'Connection refused on port 8083', 'ts': '2026-11-23T10:03:00Z'}
                    ],
                    'hypotheses': [
                        {'cause': 'Inventory service process crashed [ev_log_004]', 'category': 'cross-service', 'confidence': 0.88, 'evidence_ids': ['ev_log_004'], 'culprit_change': None}
                    ],
                    'recommended_action': 'propose_fix'
                }""",
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 5: Truncated JSON missing final braces
            {
                "id": "sample_05_truncated_unclosed_braces",
                "raw_text": """{
                    "investigation_summary": "Memory leak detected.",
                    "evidence": [{"id": "ev_metric_005", "type": "metric", "ref": "container_memory_usage", "excerpt": "98% RAM", "ts": "2026-11-23T10:04:00Z"}],
                    "hypotheses": [{"cause": "Memory leak in orders worker [ev_metric_005]", "category": "resource", "confidence": 0.85, "evidence_ids": ["ev_metric_005"]}""",
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 6: Percentage confidence values ("85%" and integer 92)
            {
                "id": "sample_06_percentage_confidence",
                "raw_text": json.dumps({
                    "investigation_summary": "Deadlock during order placement.",
                    "evidence": [{"id": "ev_log_006", "type": "log", "ref": "postgres.log", "excerpt": "deadlock detected", "ts": "2026-11-23T10:06:00Z"}],
                    "hypotheses": [
                        {"cause": "Lock contention on inventory row [ev_log_006]", "category": "code", "confidence": "92%", "evidence_ids": ["ev_log_006"]},
                        {"cause": "Secondary query timeout", "category": "code", "confidence": 40, "evidence_ids": ["ev_log_006"]}
                    ]
                }),
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 7: Missing evidence IDs on evidence items (auto-generated ID check)
            {
                "id": "sample_07_missing_evidence_ids_auto_assign",
                "raw_text": json.dumps({
                    "investigation_summary": "Payment 400 Bad Request.",
                    "evidence": [
                        {"type": "log", "ref": "payments/api.py:50", "excerpt": "Invalid currency 'USD ' with trailing space", "ts": "2026-11-23T10:07:00Z"}
                    ],
                    "hypotheses": [
                        {"cause": "Trailing space in currency string", "category": "code", "confidence": 0.89, "evidence_ids": []}
                    ]
                }),
                "expect_uncited": True,  # hypothesis has empty evidence_ids
                "needs_prompt_repair": False,
            },

            # Sample 8: Hypothesis citing unknown unreferenced evidence ID
            {
                "id": "sample_08_unreferenced_evidence_id",
                "raw_text": json.dumps({
                    "investigation_summary": "Network latency spike.",
                    "evidence": [{"id": "ev_metric_008", "type": "metric", "ref": "p99_latency", "excerpt": "450ms", "ts": "2026-11-23T10:08:00Z"}],
                    "hypotheses": [
                        {"cause": "Downstream redis saturation", "category": "dependency", "confidence": 0.70, "evidence_ids": ["ev_metric_phantom_999"]}
                    ]
                }),
                "expect_uncited": True,  # unknown evidence ID cited
                "needs_prompt_repair": False,
            },

            # Sample 9: Hypothesis with zero evidence citations (pure guess)
            {
                "id": "sample_09_pure_guess_uncited",
                "raw_text": json.dumps({
                    "investigation_summary": "Uncertain outage cause.",
                    "evidence": [],
                    "hypotheses": [
                        {"cause": "Someone probably deleted a database table without telling anyone", "category": "code", "confidence": 0.30, "evidence_ids": []}
                    ]
                }),
                "expect_uncited": True,  # zero evidence cited
                "needs_prompt_repair": False,
            },

            # Sample 10: Non-standard category mappings
            {
                "id": "sample_10_category_mapping_aliases",
                "raw_text": json.dumps({
                    "investigation_summary": "Upstream timeout cascading to gateway.",
                    "evidence": [{"id": "ev_log_010", "type": "log", "ref": "gateway/nginx.log", "excerpt": "upstream timed out", "ts": "2026-11-23T10:10:00Z"}],
                    "hypotheses": [
                        {"cause": "Cascading delay in payment service [ev_log_010]", "category": "cross-service", "confidence": 0.91, "evidence_ids": ["ev_log_010"]}
                    ]
                }),
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 11: Single hypothesis object instead of list
            {
                "id": "sample_11_single_hypothesis_dict",
                "raw_text": json.dumps({
                    "investigation_summary": "Bad deploy of orders v1.2.",
                    "evidence": [{"id": "ev_commit_011", "type": "commit", "ref": "git:abc777", "excerpt": "Merge branch feature/discounts", "ts": "2026-11-23T10:11:00Z"}],
                    "hypotheses": {
                        "cause": "Discount calculation syntax error in commit abc777 [ev_commit_011]",
                        "category": "code",
                        "confidence": 0.94,
                        "evidence_ids": ["ev_commit_011"],
                        "culprit_change": "commit_abc777"
                    }
                }),
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 12: Evidence type mapping aliases (logs, git, telemetry)
            {
                "id": "sample_12_evidence_type_aliases",
                "raw_text": json.dumps({
                    "investigation_summary": "Multi-telemetry correlation.",
                    "evidence": [
                        {"id": "ev_012_a", "type": "logs", "ref": "syslog", "excerpt": "OOM killer invoked", "ts": "2026-11-23T10:12:00Z"},
                        {"id": "ev_012_b", "type": "telemetry", "ref": "mem_gauge", "excerpt": "99% limit reached", "ts": "2026-11-23T10:12:05Z"},
                        {"id": "ev_012_c", "type": "git", "ref": "commit_888", "excerpt": "add in-memory cache", "ts": "2026-11-23T10:12:10Z"}
                    ],
                    "hypotheses": [
                        {"cause": "Unbounded cache exhausted worker memory [ev_012_a, ev_012_b]", "category": "resource", "confidence": 0.96, "evidence_ids": ["ev_012_a", "ev_012_b"], "culprit_change": "commit_888"}
                    ]
                }),
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 13: Pre-populated uncited claims list
            {
                "id": "sample_13_prepopulated_uncited_claims",
                "raw_text": json.dumps({
                    "investigation_summary": "Intermittent packet loss.",
                    "evidence": [{"id": "ev_log_013", "type": "log", "ref": "network.log", "excerpt": "SYN_SENT timeout", "ts": "2026-11-23T10:13:00Z"}],
                    "hypotheses": [{"cause": "Network routing delay [ev_log_013]", "category": "dependency", "confidence": 0.65, "evidence_ids": ["ev_log_013"]}],
                    "uncited_claims": ["[GUESS] ISP cloud peering instability suspected without external proof"]
                }),
                "expect_uncited": True,
                "needs_prompt_repair": False,
            },

            # Sample 14: Escaped newlines, quotes, and unicode in log excerpts
            {
                "id": "sample_14_escaped_newlines_and_unicode",
                "raw_text": json.dumps({
                    "investigation_summary": "UnicodeDecodeError in parser.",
                    "evidence": [{"id": "ev_log_014", "type": "log", "ref": "parser.py:88", "excerpt": "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff\n  File \"parser.py\", line 88", "ts": "2026-11-23T10:14:00Z"}],
                    "hypotheses": [{"cause": "Non-UTF8 byte in payload crashed parser [ev_log_014]", "category": "code", "confidence": 0.97, "evidence_ids": ["ev_log_014"]}]
                }),
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 15: Low confidence escalation response
            {
                "id": "sample_15_escalation_low_confidence",
                "raw_text": json.dumps({
                    "investigation_summary": "Telemetry inconclusive; multiple conflicting symptoms.",
                    "evidence": [{"id": "ev_log_015", "type": "log", "ref": "system.log", "excerpt": "Random I/O delay", "ts": "2026-11-23T10:15:00Z"}],
                    "hypotheses": [{"cause": "Unknown hardware degradation [ev_log_015]", "category": "unknown", "confidence": 0.35, "evidence_ids": ["ev_log_015"]}],
                    "recommended_action": "escalate",
                    "escalation_reason": "Confidence 0.35 is below automated remediation threshold (0.60)."
                }),
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 16: Wrapped in outer 'diagnosis' object
            {
                "id": "sample_16_wrapped_outer_key",
                "raw_text": json.dumps({
                    "diagnosis": {
                        "investigation_summary": "Port collision in payments deployment.",
                        "evidence": [{"id": "ev_log_016", "type": "log", "ref": "docker.log", "excerpt": "bind: address already in use 8082", "ts": "2026-11-23T10:16:00Z"}],
                        "hypotheses": [{"cause": "Port 8082 conflict prevented payments container startup [ev_log_016]", "category": "config", "confidence": 0.93, "evidence_ids": ["ev_log_016"]}],
                        "recommended_action": "propose_fix"
                    }
                }),
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 17: Multiple hypotheses with partial evidence coverage
            {
                "id": "sample_17_mixed_evidence_coverage",
                "raw_text": json.dumps({
                    "investigation_summary": "Database connectivity loss under load.",
                    "evidence": [{"id": "ev_metric_017", "type": "metric", "ref": "db_conn_active", "excerpt": "100/100 active connections", "ts": "2026-11-23T10:17:00Z"}],
                    "hypotheses": [
                        {"cause": "Connection pool exhausted under spike [ev_metric_017]", "category": "resource", "confidence": 0.85, "evidence_ids": ["ev_metric_017"]},
                        {"cause": "Postgres hung due to storage disk failure", "category": "dependency", "confidence": 0.25, "evidence_ids": []}
                    ]
                }),
                "expect_uncited": True,  # second hypothesis has no evidence
                "needs_prompt_repair": False,
            },

            # Sample 18: Evidence given as dictionary map instead of list
            {
                "id": "sample_18_evidence_as_dict_map",
                "raw_text": json.dumps({
                    "investigation_summary": "Bad migration lock.",
                    "evidence": {
                        "e1": {"id": "ev_log_018", "type": "log", "ref": "alembic.log", "excerpt": "Lock wait timeout", "ts": "2026-11-23T10:18:00Z"}
                    },
                    "hypotheses": [
                        {"cause": "Exclusive table lock held by unfinished migration [ev_log_018]", "category": "code", "confidence": 0.90, "evidence_ids": ["ev_log_018"]}
                    ]
                }),
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },

            # Sample 19: Malformed text that fails first parse but recovers after 1 repair round
            {
                "id": "sample_19_one_turn_repair_recovery",
                "raw_text": "I think the cause is bug in line 40 but I forgot JSON format completely. Here is cause: orders syntax error.",
                "repaired_simulated_text": json.dumps({
                    "investigation_summary": "Syntax error in orders/main.py.",
                    "evidence": [{"id": "ev_log_019", "type": "log", "ref": "orders/main.py:40", "excerpt": "SyntaxError: invalid syntax", "ts": "2026-11-23T10:19:00Z"}],
                    "hypotheses": [{"cause": "SyntaxError in orders/main.py:40 [ev_log_019]", "category": "code", "confidence": 0.99, "evidence_ids": ["ev_log_019"]}],
                    "uncited_claims": []
                }),
                "expect_uncited": False,
                "needs_prompt_repair": True,
            },

            # Sample 20: Complex multi-service cross-service RCA with culprit commit
            {
                "id": "sample_20_complex_cross_service_rca",
                "raw_text": json.dumps({
                    "investigation_summary": "Gateway 502 errors triggered by payments service serialization bug introduced in commit c99a1f.",
                    "evidence": [
                        {"id": "ev_log_020_a", "type": "log", "ref": "gateway/nginx.log", "excerpt": "502 Bad Gateway from upstream orders", "ts": "2026-11-23T10:20:00Z"},
                        {"id": "ev_log_020_b", "type": "log", "ref": "orders/main.py:112", "excerpt": "HTTP 500 received from payments /process", "ts": "2026-11-23T10:20:02Z"},
                        {"id": "ev_log_020_c", "type": "log", "ref": "payments/service.py:75", "excerpt": "AttributeError: 'NoneType' object has no attribute 'get'", "ts": "2026-11-23T10:20:03Z"},
                        {"id": "ev_commit_020", "type": "commit", "ref": "c99a1f2b4", "excerpt": "refactor: simplify payment payload schema", "ts": "2026-11-23T09:55:00Z"}
                    ],
                    "hypotheses": [
                        {
                            "cause": "Payments service schema mismatch in commit c99a1f causes 500s cascading to orders and gateway [ev_log_020_c, ev_commit_020]",
                            "category": "cross_service",
                            "confidence": 0.96,
                            "evidence_ids": ["ev_log_020_a", "ev_log_020_b", "ev_log_020_c", "ev_commit_020"],
                            "culprit_change": "c99a1f2b4"
                        },
                        {
                            "cause": "Gateway buffer overflow [ev_log_020_a]",
                            "category": "resource",
                            "confidence": 0.15,
                            "evidence_ids": ["ev_log_020_a"]
                        }
                    ],
                    "uncited_claims": [],
                    "recommended_action": "propose_fix"
                }),
                "expect_uncited": False,
                "needs_prompt_repair": False,
            },
        ]

    def test_twenty_sample_runs_schema_validity_and_citation_flagging(self):
        """Execute all 20 diverse sample runs to verify 100% schema validity and citation flagging."""
        total_runs = len(self.samples)
        self.assertEqual(total_runs, 20, "Must evaluate exactly 20 sample runs.")

        valid_runs = 0
        citation_checked = 0

        for sample in self.samples:
            sample_id = sample["id"]
            raw_text = sample["raw_text"]
            needs_prompt_repair = sample.get("needs_prompt_repair", False)
            expect_uncited = sample.get("expect_uncited", False)

            diagnosis = None

            if not needs_prompt_repair:
                # Direct parse with self-healing
                diagnosis, was_repaired = parse_structured_diagnosis(raw_text)
            else:
                # Triggers 1-turn repair prompt simulation
                try:
                    diagnosis, was_repaired = parse_structured_diagnosis(raw_text)
                except ValueError as parse_err:
                    repair_prompt = build_repair_prompt(str(parse_err), raw_text)
                    self.assertIn("REQUIRED FORMAT:", repair_prompt)
                    # Simulated LLM 1-turn repair response
                    repaired_text = sample["repaired_simulated_text"]
                    diagnosis, was_repaired = parse_structured_diagnosis(repaired_text)

            # Assert Diagnosis is valid StructuredDiagnosis
            self.assertIsInstance(
                diagnosis,
                StructuredDiagnosis,
                f"Sample {sample_id} failed to produce StructuredDiagnosis instance",
            )

            # Assert 100% of Hypotheses are schema-valid Hypothesis models
            for hyp in diagnosis.hypotheses:
                self.assertIsInstance(hyp, Hypothesis, f"Sample {sample_id}: item is not Hypothesis model")
                self.assertIsInstance(hyp.cause, str)
                self.assertGreater(len(hyp.cause), 0)
                self.assertIn(hyp.category, ("code", "config", "resource", "cross_service", "dependency", "unknown"))
                self.assertGreaterEqual(hyp.confidence, 0.0)
                self.assertLessEqual(hyp.confidence, 1.0)
                self.assertIsInstance(hyp.evidence_ids, list)

            # Assert 100% of Evidence items are schema-valid Evidence models
            for ev in diagnosis.evidence:
                self.assertIsInstance(ev, Evidence, f"Sample {sample_id}: item is not Evidence model")
                self.assertIsInstance(ev.id, str)
                self.assertGreater(len(ev.id), 0)
                self.assertIn(ev.type, ("log", "metric", "commit", "config", "past_incident"))
                self.assertIsInstance(ev.ref, str)
                self.assertIsInstance(ev.excerpt, str)
                self.assertIsInstance(ev.ts, str)

            # Assert citation flagging: any claim without an evidence ID is flagged
            if expect_uncited:
                self.assertGreater(
                    len(diagnosis.uncited_claims),
                    0,
                    f"Sample {sample_id} was expected to have flagged uncited claims/guesses, but uncited_claims was empty.",
                )
                citation_checked += 1

            valid_runs += 1

        # Final acceptance criteria check
        schema_valid_rate = (valid_runs / total_runs) * 100.0
        self.assertEqual(
            schema_valid_rate,
            100.0,
            f"Acceptance Criteria failed: expected 100% schema validity, got {schema_valid_rate}%",
        )
        self.assertGreaterEqual(citation_checked, 4, "Must test and verify citation flagging across multiple samples.")


if __name__ == "__main__":
    unittest.main()
