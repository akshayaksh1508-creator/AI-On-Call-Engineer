"""Configuration and Service URL discovery for Target App Services."""

import os
from pathlib import Path


class Settings:
    # Service Ports
    GATEWAY_PORT: int = int(os.environ.get("GATEWAY_PORT", "8080"))
    ORDERS_PORT: int = int(os.environ.get("ORDERS_PORT", "8081"))
    PAYMENTS_PORT: int = int(os.environ.get("PAYMENTS_PORT", "8082"))
    INVENTORY_PORT: int = int(os.environ.get("INVENTORY_PORT", "8083"))
    PROMETHEUS_PORT: int = int(os.environ.get("PROMETHEUS_PORT", "9090"))

    # Service Upstream Base URLs
    ORDERS_SERVICE_URL: str = os.environ.get("ORDERS_SERVICE_URL", f"http://127.0.0.1:{ORDERS_PORT}")
    PAYMENTS_SERVICE_URL: str = os.environ.get("PAYMENTS_SERVICE_URL", f"http://127.0.0.1:{PAYMENTS_PORT}")

    # Database Configuration (PostgreSQL)
    POSTGRES_HOST: str = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    POSTGRES_PORT: int = int(os.environ.get("POSTGRES_PORT", "5432"))
    POSTGRES_USER: str = os.environ.get("POSTGRES_USER", "app_user")
    POSTGRES_PASSWORD: str = os.environ.get("POSTGRES_PASSWORD", "app_password")
    POSTGRES_DB: str = os.environ.get("POSTGRES_DB", "target_db")

    # Local fallback sqlite DB path (if PostgreSQL is not running)
    SQLITE_FALLBACK_PATH: Path = (
        Path(__file__).resolve().parent.parent.parent / "data" / "target_app_orders.db"
    )

    # Service Versions (dynamically read from version.txt if available)
    @property
    def VERSION(self) -> str:
        version_file = Path(__file__).resolve().parent.parent / "version.txt"
        if version_file.exists():
            v = version_file.read_text(encoding="utf-8").strip()
            if v:
                return v
        return os.environ.get("APP_VERSION", "1.0.0")


settings = Settings()
