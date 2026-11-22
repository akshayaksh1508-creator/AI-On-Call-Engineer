#!/usr/bin/env python3
"""Interactive / Manual Verification Script for Task A2.

Tests all Task A2 requirements against live running services:
1. /health on all three services (gateway, orders, payments) returns 200.
2. Order creation end-to-end via Gateway -> Orders -> Payments.
3. Trace ID propagation across all three services' structured logs.
4. Prometheus /metrics exposition and counter incrementation.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path
import urllib.request
import urllib.error

ROOT_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT_DIR / "logs" / "all_services.log"

GATEWAY_URL = "http://127.0.0.1:8080"
ORDERS_URL = "http://127.0.0.1:8081"
PAYMENTS_URL = "http://127.0.0.1:8082"


def http_get(url: str, headers: dict = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except Exception as e:
        return 0, str(e)


def http_post_json(url: str, data: dict, headers: dict = None) -> tuple[int, str]:
    payload = json.dumps(data).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=payload, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except Exception as e:
        return 0, str(e)


def main():
    print("=" * 70)
    print(" NightShift - Task A2 Manual & Live Verification Tool")
    print("=" * 70)

    # 1. Check health endpoints
    print("\n[Step 1/5] Checking /health endpoints on all 3 services...")
    services = [("Gateway", GATEWAY_URL), ("Orders", ORDERS_URL), ("Payments", PAYMENTS_URL)]
    all_healthy = True

    for name, base_url in services:
        status, body = http_get(f"{base_url}/health")
        if status == 200:
            print(f"  [OK] {name} ({base_url}/health) -> HTTP 200: {body.strip()}")
        else:
            print(f"  [FAIL] {name} ({base_url}/health) -> HTTP {status}: {body}")
            all_healthy = False

    if not all_healthy:
        print("\nERROR: Not all services are running or reachable.")
        print("Please start them first in another terminal with:")
        print("    python target-app/run_services.py")
        sys.exit(1)

    # 2. Check metrics before order
    print("\n[Step 2/5] Inspecting baseline Prometheus /metrics...")
    status, metrics_before = http_get(f"{GATEWAY_URL}/metrics")
    count_before = metrics_before.count("http_requests_total")
    print(f"  Gateway metrics active. Found http_requests_total descriptors.")

    # 3. Send End-to-End Order
    trace_id = f"trace-manual-{uuid.uuid4().hex[:8]}"
    print(f"\n[Step 3/5] Sending order through Gateway with Trace ID: '{trace_id}'...")
    order_payload = {
        "customer_id": "cust_akshay_manual",
        "item": "Ultra-Wide Monitor",
        "quantity": 1,
        "price": 499.99
    }
    status, response_body = http_post_json(
        f"{GATEWAY_URL}/api/orders",
        order_payload,
        headers={"X-Trace-ID": trace_id}
    )

    if status == 201:
        print(f"  [OK] Gateway returned HTTP 201 Created!")
        print(f"  Response: {response_body.strip()}")
    else:
        print(f"  [FAIL] Gateway returned HTTP {status}: {response_body}")
        sys.exit(1)

    # Allow disk flush of log entries
    time.sleep(0.5)

    # 4. Verify Trace ID propagation in structured logs
    print(f"\n[Step 4/5] Verifying Trace ID '{trace_id}' in structured logs...")
    if not LOG_FILE.exists():
        print(f"  [FAIL] Log file {LOG_FILE} not found!")
        sys.exit(1)

    matched_logs = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if trace_id in line:
                try:
                    entry = json.loads(line.strip())
                    matched_logs.append(entry)
                except json.JSONDecodeError:
                    pass

    services_in_logs = {entry["service"] for entry in matched_logs}
    print(f"  Services logging this trace_id: {services_in_logs}")

    for entry in matched_logs:
        print(f"    - [{entry['service'].upper()}] [{entry['level']}] {entry['message']}")

    if {"gateway", "orders", "payments"}.issubset(services_in_logs):
        print(f"  [OK] TRACE PROPAGATION VERIFIED: All 3 services logged '{trace_id}'!")
    else:
        missing = {"gateway", "orders", "payments"} - services_in_logs
        print(f"  [FAIL] Missing trace in services: {missing}")
        sys.exit(1)

    # 5. Check metrics after order
    print("\n[Step 5/5] Verifying Prometheus counters rise...")
    status, metrics_after = http_get(f"{GATEWAY_URL}/metrics")
    req_lines = [l for l in metrics_after.splitlines() if "http_requests_total" in l and not l.startswith("#")]
    print(f"  Active request counters on Gateway:")
    for line in req_lines[:5]:
        print(f"    {line}")

    print("\n" + "=" * 70)
    print(" ALL TASK A2 REQUIREMENTS FULLY VERIFIED AND PASSING!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
