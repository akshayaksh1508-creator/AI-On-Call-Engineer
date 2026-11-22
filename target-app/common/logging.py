"""Structured JSON Logging with Trace Context for NightShift Services.

Rule (Section 3 Telemetry):
"Every log line has service, trace id, timestamp"
Format: {"service": "...", "trace_id": "...", "timestamp": "...", "level": "INFO", "message": "..."}
"""

import datetime
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Shared log directory for local inspection & platform_api
LOGS_DIR = Path(os.environ.get("LOGS_DIR", Path(__file__).resolve().parent.parent.parent / "logs"))
LOGS_DIR.mkdir(parents=True, exist_ok=True)


class JsonFormatter(logging.Formatter):
    """Formats log records as structured JSON."""

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        trace_id = getattr(record, "trace_id", "none")
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        log_entry: Dict[str, Any] = {
            "service": self.service_name,
            "trace_id": trace_id,
            "timestamp": timestamp,
            "level": record.levelname,
            "message": record.getMessage(),
        }

        # Include optional structured extra fields
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_entry.update(record.extra_fields)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logger(service_name: str) -> logging.Logger:
    """Configures a JSON logger writing to stdout and a shared log file."""
    logger = logging.getLogger(service_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # Avoid duplicate handlers if re-initialized
    if logger.handlers:
        return logger

    formatter = JsonFormatter(service_name=service_name)

    # 1. Console handler (stdout)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    # 2. File handler in logs directory
    service_log_file = LOGS_DIR / f"{service_name}.log"
    file_handler = logging.FileHandler(service_log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 3. Combined all-services log file
    combined_log_file = LOGS_DIR / "all_services.log"
    combined_handler = logging.FileHandler(combined_log_file, encoding="utf-8")
    combined_handler.setFormatter(formatter)
    logger.addHandler(combined_handler)

    return logger
