"""Scratch verification script for Real Platform API Endpoints (Day 2 Task A2).

Demonstrates and verifies:
1. /logs/query: Fast filtering by service, level, and text substring.
2. Direct Grep Parity: Verifies log query counts match a direct line-by-line file grep.
3. /metrics/query: Real/fallback Prometheus time series metrics query.
4. /changes: Real deployment history from data/changes.json.
5. Response Latency: Asserts all responses return in strictly under 500 ms.

Usage:
    python scratch/test_live_endpoints.py
"""

import json
from pathlib import Path
import sys
import time

# Add project root to sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from starlette.testclient import TestClient
from platform_api.app import create_platform_api_app


def run_live_endpoints_test():
    print("=" * 75)
    print("NightShift Platform API: Real Endpoints Verification (Day 2 Task A2)")
    print("=" * 75)

    app = create_platform_api_app(mode="real")
    client = TestClient(app)

    # -------------------------------------------------------------------------
    # 1. Real /logs/query Endpoint & Direct Grep Parity
    # -------------------------------------------------------------------------
    print("\n[1/3] Testing /logs/query against real logs directory...")
    logs_dir = ROOT_DIR / "logs"
    orders_log_file = logs_dir / "orders.log"
    all_log_file = logs_dir / "all_services.log"

    assert logs_dir.exists(), f"Logs directory {logs_dir} must exist."

    # Direct grep of orders.log for ERROR lines
    grep_error_count = 0
    if orders_log_file.exists():
        with open(orders_log_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"level": "ERROR"' in line or '"level":"ERROR"' in line or '"ERROR"' in line:
                    grep_error_count += 1
    elif all_log_file.exists():
        with open(all_log_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"orders"' in line and '"ERROR"' in line:
                    grep_error_count += 1

    t0 = time.perf_counter()
    resp_logs = client.get("/logs/query", params={"service": "orders", "level": "ERROR", "limit": 1000})
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert resp_logs.status_code == 200, f"Expected 200, got {resp_logs.status_code}"
    logs_data = resp_logs.json()
    print(f"      Latency: {latency_ms:.2f} ms (< 500 ms threshold)")
    print(f"      Returned {len(logs_data)} ERROR logs for 'orders'")
    print(f"      Direct file grep found: {grep_error_count} ERROR lines")

    assert latency_ms < 500.0, f"Response latency {latency_ms:.2f} ms exceeded 500 ms!"
    # Ensure returned count matches grep count (or limit cap)
    expected_count = min(grep_error_count, 1000)
    assert len(logs_data) == expected_count, (
        f"Grep parity failure: endpoint returned {len(logs_data)}, grep found {expected_count}"
    )
    print("      [PASS] /logs/query count exactly matches direct file grep count!")

    # Test text search substring
    t0 = time.perf_counter()
    resp_text = client.get("/logs/query", params={"service": "orders", "text": "failed with status"})
    lat_text = (time.perf_counter() - t0) * 1000.0
    text_data = resp_text.json()
    print(f"      Text query ('failed with status') returned {len(text_data)} logs in {lat_text:.2f} ms")
    assert lat_text < 500.0
    if text_data:
        assert any("failed with status" in (l.get("message", "") + " " + json.dumps(l)).lower() for l in text_data)
    print("      [PASS] Substring text filtering operational.")

    # -------------------------------------------------------------------------
    # 2. Real /metrics/query Endpoint
    # -------------------------------------------------------------------------
    print("\n[2/3] Testing /metrics/query endpoint...")
    t0 = time.perf_counter()
    resp_metrics = client.get("/metrics/query", params={"metric_name": "http_requests_total"})
    lat_metrics = (time.perf_counter() - t0) * 1000.0

    assert resp_metrics.status_code == 200
    metrics_data = resp_metrics.json()
    print(f"      Latency: {lat_metrics:.2f} ms (< 500 ms threshold)")
    print(f"      Metrics query status: {metrics_data.get('status')}")
    assert lat_metrics < 500.0
    assert metrics_data.get("status") == "success"
    assert "data" in metrics_data
    print("      [PASS] /metrics/query returns valid Prometheus schema.")

    # -------------------------------------------------------------------------
    # 3. Real /changes Endpoint
    # -------------------------------------------------------------------------
    print("\n[3/3] Testing /changes endpoint...")
    t0 = time.perf_counter()
    resp_changes = client.get("/changes", params={"limit": 5})
    lat_changes = (time.perf_counter() - t0) * 1000.0

    assert resp_changes.status_code == 200
    changes_data = resp_changes.json()
    print(f"      Latency: {lat_changes:.2f} ms (< 500 ms threshold)")
    print(f"      Retrieved {len(changes_data)} deployment changes from data/changes.json")
    assert lat_changes < 500.0
    assert isinstance(changes_data, list)
    if changes_data:
        first = changes_data[0]
        print(f"      Most recent change: {first.get('id')} ({first.get('service')}, v: {first.get('version')})")
        assert "id" in first
        assert "service" in first
        assert "timestamp" in first
    print("      [PASS] /changes returns structured change events.")

    print("\n" + "=" * 75)
    print("SUCCESS: Day 2 Task A2 Verification Passed!")
    print("  • /logs/query matched direct file grep counts.")
    print("  • All endpoint responses completed strictly under 500 ms.")
    print("  • /metrics/query and /changes adhere to shared contracts.")
    print("=" * 75)


if __name__ == "__main__":
    run_live_endpoints_test()
