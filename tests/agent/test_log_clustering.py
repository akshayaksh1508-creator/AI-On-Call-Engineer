import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import unittest

from agent.log_clustering import cluster_logs, first_error_by_service, normalize


class ClusterTests(unittest.TestCase):
    def test_normalize_merges_ids_numbers_ips(self):
        a = normalize("Timeout after 2000ms request_id=abc123 from 10.0.0.5:8080")
        b = normalize("Timeout after 50ms request_id=zzz999 from 10.0.0.9:9000")
        self.assertEqual(a, b)

    def test_cluster_counts_first_ts_and_filters_info(self):
        logs = [
            {"ts": 10, "service": "orders", "level": "ERROR", "message": "pool 1 exhausted id=aaaaaaaa"},
            {"ts": 12, "service": "orders", "level": "ERROR", "message": "pool 2 exhausted id=bbbbbbbb"},
            {"ts": 5, "service": "gateway", "level": "WARNING", "message": "slow 300ms"},
            {"ts": 1, "service": "gateway", "level": "INFO", "message": "ok"},
        ]
        cl = cluster_logs(logs)
        self.assertEqual(len(cl), 2)
        self.assertEqual((cl[0]["service"], cl[0]["count"], cl[0]["first_ts"], cl[0]["last_ts"]), ("orders", 2, 10, 12))
        self.assertEqual(first_error_by_service(cl), {"orders": 10, "gateway": 5})
        self.assertEqual(len(cluster_logs(logs, bad_only=False)), 3)


if __name__ == "__main__":
    unittest.main()
