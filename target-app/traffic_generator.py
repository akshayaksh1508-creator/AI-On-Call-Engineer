#!/usr/bin/env python3
"""NightShift Target App Steady Traffic Generator.

Sends steady synthetic traffic (default: 10 requests/sec) to the Gateway service.
Requirement (Section 14 Task A3):
"Traffic generator (about 10 requests per second)"
"How to test: 10 minutes of traffic gives error rate under 1%"
"""

import argparse
import datetime
import json
import random
import signal
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

# Realistic test data catalog
CATALOG = [
    ("Laptop Pro 16", 1999.99),
    ("Mechanical Keyboard", 129.99),
    ("Wireless Mouse", 49.99),
    ("4K Gaming Monitor", 449.99),
    ("Noise-Canceling Headphones", 279.99),
    ("USB-C Docking Station", 89.99),
    ("Ergonomic Chair", 349.99),
    ("Webcam 4K", 99.99),
    ("External SSD 2TB", 159.99),
    ("Smartphone Stand", 19.99),
]

CUSTOMERS = [f"cust_{i:04d}" for i in range(1, 100)]


class TrafficStats:
    def __init__(self):
        self.sent = 0
        self.success = 0
        self.failed = 0
        self.latencies: List[float] = []
        self.start_time = time.time()

    def record_success(self, latency: float):
        self.sent += 1
        self.success += 1
        self.latencies.append(latency)

    def record_failure(self, latency: float):
        self.sent += 1
        self.failed += 1
        self.latencies.append(latency)

    @property
    def error_rate(self) -> float:
        if self.sent == 0:
            return 0.0
        return (self.failed / self.sent) * 100.0

    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        return (sum(self.latencies) / len(self.latencies)) * 1000.0

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_l = sorted(self.latencies)
        idx = int(len(sorted_l) * 0.95)
        return sorted_l[min(idx, len(sorted_l) - 1)] * 1000.0


def send_order_request(target_url: str, timeout: float = 5.0) -> tuple[bool, float]:
    """Sends a single randomized order request to the target app gateway."""
    item, price = random.choice(CATALOG)
    customer = random.choice(CUSTOMERS)
    qty = random.randint(1, 3)

    payload = json.dumps({
        "customer_id": customer,
        "item": item,
        "quantity": qty,
        "price": price,
    }).encode("utf-8")

    trace_id = f"trace-gen-{uuid.uuid4().hex[:10]}"
    headers = {
        "Content-Type": "application/json",
        "X-Trace-ID": trace_id,
        "User-Agent": "NightShift-TrafficGenerator/1.0",
    }

    req = urllib.request.Request(target_url, data=payload, headers=headers, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency = time.time() - t0
            return (resp.status in (200, 201), latency)
    except urllib.error.HTTPError as err:
        latency = time.time() - t0
        return (False, latency)
    except Exception:
        latency = time.time() - t0
        return (False, latency)


class TrafficGenerator:
    def __init__(self, target_url: str, rate: float = 10.0, duration: Optional[float] = None):
        self.target_url = target_url
        self.rate = rate  # requests per second
        self.duration = duration  # seconds, or None for infinite
        self.stats = TrafficStats()
        self.running = True
        self.interval = 1.0 / rate if rate > 0 else 0.1

    def stop(self, *args):
        self.running = False

    def run(self) -> int:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        print("=" * 70)
        print(" NightShift Traffic Generator Active")
        print(f" Target:    {self.target_url}")
        print(f" Rate:      {self.rate:.1f} requests/sec (interval: {self.interval * 1000:.1f}ms)")
        duration_str = f"{self.duration}s ({self.duration / 60:.1f} mins)" if self.duration else "Indefinite (Ctrl+C to stop)"
        print(f" Duration:  {duration_str}")
        print("=" * 70)

        start_time = time.time()
        last_report_time = start_time

        # Worker pool for non-blocking HTTP dispatch
        executor = ThreadPoolExecutor(max_workers=max(20, int(self.rate * 2)))

        def on_complete(future):
            success, latency = future.result()
            if success:
                self.stats.record_success(latency)
            else:
                self.stats.record_failure(latency)

        try:
            while self.running:
                now = time.time()
                elapsed = now - start_time

                if self.duration and elapsed >= self.duration:
                    break

                # Dispatch request
                fut = executor.submit(send_order_request, self.target_url)
                fut.add_done_callback(on_complete)

                # Periodic progress reporting (every 5 seconds)
                if now - last_report_time >= 5.0:
                    current_rate = self.stats.sent / elapsed if elapsed > 0 else 0.0
                    mins, secs = divmod(int(elapsed), 60)
                    print(
                        f"[{mins:02d}:{secs:02d}] Sent: {self.stats.sent:5d} | "
                        f"Success: {self.stats.success:5d} | Failed: {self.stats.failed:3d} | "
                        f"Error Rate: {self.stats.error_rate:5.2f}% | "
                        f"Rate: {current_rate:4.1f} rps | "
                        f"Avg Latency: {self.stats.avg_latency_ms:5.1f}ms"
                    )
                    last_report_time = now

                # Sleep to maintain desired request rate
                time.sleep(self.interval)

        finally:
            executor.shutdown(wait=True)

        total_elapsed = time.time() - start_time
        return self._print_summary(total_elapsed)

    def _print_summary(self, elapsed: float) -> int:
        print("\n" + "=" * 70)
        print(" NightShift Traffic Generator Summary Report")
        print("=" * 70)
        mins, secs = divmod(int(elapsed), 60)
        print(f" Total Duration:   {mins:02d}m {secs:02d}s ({elapsed:.2f}s)")
        print(f" Requests Sent:    {self.stats.sent}")
        print(f" Succeeded (201):  {self.stats.success}")
        print(f" Failed:           {self.stats.failed}")
        print(f" Achieved Rate:    {self.stats.sent / elapsed:.2f} requests/sec" if elapsed > 0 else "")
        print(f" Error Rate:       {self.stats.error_rate:.2f}%")
        print(f" Avg Latency:      {self.stats.avg_latency_ms:.1f} ms")
        print(f" p95 Latency:      {self.stats.p95_latency_ms:.1f} ms")

        # Architectural validation criteria: error rate < 1.0%
        if self.stats.error_rate < 1.0 and self.stats.sent > 0:
            print("\n STATUS: [PASS] Error rate is under 1.0% (Architecture Rule Satisfied)")
            print("=" * 70 + "\n")
            return 0
        elif self.stats.sent == 0:
            print("\n STATUS: [WARNING] No requests were dispatched.")
            print("=" * 70 + "\n")
            return 1
        else:
            print(f"\n STATUS: [FAIL] Error rate {self.stats.error_rate:.2f}% exceeds 1.0% threshold!")
            print("=" * 70 + "\n")
            return 1


def main():
    parser = argparse.ArgumentParser(description="NightShift Steady Traffic Generator (10 rps)")
    parser.add_argument(
        "--target",
        default="http://127.0.0.1:8080/api/orders",
        help="Target URL for order creation (default: http://127.0.0.1:8080/api/orders)",
    )
    parser.add_argument(
        "--rate",
        "-r",
        type=float,
        default=10.0,
        help="Target request rate in requests per second (default: 10.0)",
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=float,
        default=None,
        help="Duration in seconds (e.g. 600 for 10 minutes). Default: run indefinitely until Ctrl+C.",
    )
    args = parser.parse_args()

    gen = TrafficGenerator(target_url=args.target, rate=args.rate, duration=args.duration)
    sys.exit(gen.run())


if __name__ == "__main__":
    main()
