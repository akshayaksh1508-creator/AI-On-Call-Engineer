"""Tiny helper the target services import to honour fault-injected config.

Copy this file next to each service (or into a shared package). The services only
read normal-looking config variables; they never know a 'fault' exists.
"""
from __future__ import annotations

import os
import time


def env_str(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def env_int(name: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def delay_ms(name: str) -> None:
    """Sleep for the number of milliseconds in env var `name` (0 = no delay)."""
    ms = env_int(name, 0)
    if ms > 0:
        time.sleep(ms / 1000.0)


def payments_response(payload: dict) -> dict:
    """Schema v2 renames `amount` (float) to `amount_cents` (int) - breaks old consumers."""
    if env_str("PAYMENTS_RESPONSE_SCHEMA", "v1") == "v2" and "amount" in payload:
        out = dict(payload)
        out["amount_cents"] = int(round(float(out.pop("amount")) * 100))
        return out
    return payload
