"""faults component package.

Owner: Person A (Systems & Proof)
Provides the Fault Injection Framework, catalog manifests, and ground-truth definitions.
"""

from faults.manifest import FaultManifest
from faults.injector import FaultInjector, injector

__all__ = [
    "FaultManifest",
    "FaultInjector",
    "injector",
]
