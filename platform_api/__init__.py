"""platform_api component package.

Owner: Person A (Systems & Proof)
Provides the unified Platform API interface, live and fixture-backed FastAPI servers,
and PlatformClient implementations for all 9 diagnostic and remediation tools (Day 1 Task A4 & Day 2 Task A2).
"""

from typing import Optional
from platform_api.client import PlatformClient
from platform_api.fixture_client import FixtureClient
from platform_api.stub_client import StubClient
from platform_api.real_client import RealPlatformClient
from platform_api.app import create_platform_api_app, app as PlatformAPIApp
from platform_api.stub_app import app as StubPlatformAPI

__all__ = [
    "PlatformClient",
    "FixtureClient",
    "StubClient",
    "RealPlatformClient",
    "PlatformAPIApp",
    "StubPlatformAPI",
    "create_platform_api_app",
    "create_platform_client",
]


def create_platform_client(
    mode: str = "real",
    fixture_bundle: str = "fault_001_bad_deploy",
    base_url: Optional[str] = None,
) -> PlatformClient:
    """Factory creating a PlatformClient instance.

    Modes:
      - 'real' (default): Live client operating against real log files, Prometheus, and changes.json.
      - 'fixture': Offline fixture-backed client.
      - 'stub': In-process or HTTP client communicating with StubPlatformAPI.
    """
    if mode == "real":
        return RealPlatformClient()
    elif mode == "fixture":
        return FixtureClient(fixture_bundle=fixture_bundle)
    elif mode == "stub":
        return StubClient(base_url=base_url, fixture_bundle=fixture_bundle)
    else:
        raise ValueError(f"Unknown client mode: '{mode}'. Expected 'real', 'fixture', or 'stub'.")
