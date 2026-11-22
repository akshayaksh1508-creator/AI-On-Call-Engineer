"""Package alias mapping `target_app` inside `target-app` directory."""
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent)]
