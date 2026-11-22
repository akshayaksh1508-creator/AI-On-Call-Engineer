"""Runs all three target app microservices concurrently for local development/testing."""

import multiprocessing
import signal
import sys
import time
import uvicorn
from target_app.common.config import settings
from target_app.common.logging import setup_logger

logger = setup_logger("service_runner")


def run_payments(port: int = settings.PAYMENTS_PORT):
    from target_app.services.payments.app import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def run_orders(port: int = settings.ORDERS_PORT):
    from target_app.services.orders.app import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def run_gateway(port: int = settings.GATEWAY_PORT):
    from target_app.services.gateway.app import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main():
    processes = []
    print(f"Starting NightShift Target App Services...")
    print(f"  - Payments Service: http://127.0.0.1:{settings.PAYMENTS_PORT}")
    print(f"  - Orders Service:   http://127.0.0.1:{settings.ORDERS_PORT}")
    print(f"  - Gateway Service:  http://127.0.0.1:{settings.GATEWAY_PORT}")

    p_pay = multiprocessing.Process(target=run_payments, daemon=True)
    p_ord = multiprocessing.Process(target=run_orders, daemon=True)
    p_gw = multiprocessing.Process(target=run_gateway, daemon=True)

    processes.extend([p_pay, p_ord, p_gw])

    for p in processes:
        p.start()

    print("All 3 services are active. Press Ctrl+C to terminate.")

    try:
        while True:
            time.sleep(1)
            for p in processes:
                if not p.is_alive():
                    print(f"Process {p.name} exited unexpectedly.")
                    sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutting down services...")
        for p in processes:
            p.terminate()
            p.join()
        print("All services stopped.")


if __name__ == "__main__":
    main()
