"""Package alias mapping `target_app` to the `target-app` directory."""
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent / "target-app")]
