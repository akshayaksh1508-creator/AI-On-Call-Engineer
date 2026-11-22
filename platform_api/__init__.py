"""platform_api component package.

Owner: Person A (Systems & Proof)
Provides the unified Platform API interface, FastAPI stub server,
and offline FixtureClient implementing all 9 diagnostic and remediation tools.
"""

from typing import Optional
from platform_api.client import PlatformClient
from platform_api.fixture_client import FixtureClient
from platform_api.stub_client import StubClient
from platform_api.stub_app import create_platform_api_app, app as StubPlatformAPI

__all__ = [
    "PlatformClient",
    "FixtureClient",
    "StubClient",
    "StubPlatformAPI",
    "create_platform_api_app",
    "create_platform_client",
]


def create_platform_client(
    mode: str = "fixture",
    fixture_bundle: str = "fault_001_bad_deploy",
    base_url: Optional[str] = None,
) -> PlatformClient:
    """Factory creating a PlatformClient instance.

    Modes:
      - 'fixture' (default): Offline fixture-backed client.
      - 'stub': In-process or HTTP client communicating with StubPlatformAPI.
    """
    if mode == "fixture":
        return FixtureClient(fixture_bundle=fixture_bundle)
    elif mode == "stub":
        return StubClient(base_url=base_url, fixture_bundle=fixture_bundle)
    else:
        raise ValueError(f"Unknown client mode: '{mode}'. Expected 'fixture' or 'stub'.")
