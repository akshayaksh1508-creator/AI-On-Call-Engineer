"""Runs all three target app microservices concurrently for local development/testing."""

import multiprocessing
import os
import signal
import sys
import time
from pathlib import Path

# Ensure repository root is in sys.path and PYTHONPATH for main & child processes
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

target_app_dir = Path(__file__).resolve().parent
if str(target_app_dir) not in sys.path:
    sys.path.insert(0, str(target_app_dir))

os.environ["PYTHONPATH"] = (
    str(ROOT_DIR) + os.pathsep + str(target_app_dir) + os.pathsep + os.environ.get("PYTHONPATH", "")
).rstrip(os.pathsep)

import uvicorn
from target_app.common.config import settings
from target_app.common.logging import setup_logger

logger = setup_logger("service_runner")


def _init_child_process():
    """Ensure child process has correct pathing on Windows spawn."""
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def run_payments(port: int = settings.PAYMENTS_PORT):
    _init_child_process()
    from target_app.services.payments.app import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def run_orders(port: int = settings.ORDERS_PORT):
    _init_child_process()
    from target_app.services.orders.app import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def run_gateway(port: int = settings.GATEWAY_PORT):
    _init_child_process()
    from target_app.services.gateway.app import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def free_ports(ports):
    """Automatically free ports if previously orphaned processes are still holding them."""
    import subprocess
    current_pid = os.getpid()
    for port in ports:
        try:
            if sys.platform == "win32":
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"],
                    capture_output=True, text=True, check=False
                )
                for line in res.stdout.strip().splitlines():
                    pid = line.strip()
                    if pid.isdigit() and int(pid) != current_pid:
                        subprocess.run(
                            ["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"],
                            capture_output=True, check=False
                        )
        except Exception:
            pass


def main():
    # Support Windows multiprocessing spawn freeze
    multiprocessing.freeze_support()

    # Free ports if any lingering processes are listening
    free_ports([settings.PAYMENTS_PORT, settings.ORDERS_PORT, settings.GATEWAY_PORT])

    print("Starting NightShift Target App Services...")
    print(f"  - Payments Service: http://127.0.0.1:{settings.PAYMENTS_PORT}")
    print(f"  - Orders Service:   http://127.0.0.1:{settings.ORDERS_PORT}")
    print(f"  - Gateway Service:  http://127.0.0.1:{settings.GATEWAY_PORT}")

    p_pay = multiprocessing.Process(target=run_payments, daemon=True)
    p_ord = multiprocessing.Process(target=run_orders, daemon=True)
    p_gw = multiprocessing.Process(target=run_gateway, daemon=True)

    processes = [p_pay, p_ord, p_gw]

    for p in processes:
        p.start()

    print("\nAll 3 services are active and ready for requests.")
    print("Press Ctrl+C to stop all services.\n")

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
            if p.is_alive():
                p.terminate()
                p.join(timeout=2)
        print("All services stopped.")


if __name__ == "__main__":
    main()
