"""NightShift Core Shared Contracts.

Owner: Shared (Person A & Person B)
Provides immutable contract models and schema loaders.
Version: 1.0.0 (Frozen on Day 6 per Section 4 & Day 6 Task B3)
"""

import json
from pathlib import Path
from typing import Any, Dict

CONTRACTS_VERSION: str = "1.0.0"
CONTRACTS_FROZEN: bool = True

from contracts.models import (
    Incident,
    Evidence,
    Hypothesis,
    FixProposal,
    VerificationResult,
    RunRecord,
    ChangeRecord,
    CommitRecord,
    ServiceNode,
    ServiceMap,
    FixProposalReceipt,
)

__all__ = [
    "CONTRACTS_VERSION",
    "CONTRACTS_FROZEN",
    "Incident",
    "Evidence",
    "Hypothesis",
    "FixProposal",
    "VerificationResult",
    "RunRecord",
    "ChangeRecord",
    "CommitRecord",
    "ServiceNode",
    "ServiceMap",
    "FixProposalReceipt",
    "get_schema",
    "load_fixture_bundle",
]

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def get_schema(model_name: str) -> Dict[str, Any]:
    """Retrieve raw JSON Schema for a contract model."""
    schema_path = SCHEMAS_DIR / f"{model_name}.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema for '{model_name}' not found at {schema_path}")
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_fixture_bundle(bundle_name: str = "fault_001_bad_deploy") -> Dict[str, Any]:
    """Load all artifacts of a recorded incident fixture bundle into memory."""
    bundle_path = FIXTURES_DIR / bundle_name
    if not bundle_path.exists():
        # Fallback to faults/fixtures if placed there
        alt_path = Path(__file__).resolve().parent.parent / "faults" / "fixtures" / bundle_name
        if alt_path.exists():
            bundle_path = alt_path
        else:
            raise FileNotFoundError(f"Fixture bundle '{bundle_name}' not found at {bundle_path}")

    bundle: Dict[str, Any] = {"name": bundle_name, "path": str(bundle_path)}

    # Incident
    incident_file = bundle_path / "incident.json"
    if incident_file.exists():
        with open(incident_file, "r", encoding="utf-8") as f:
            bundle["incident"] = json.load(f)

    # Logs
    logs_file = bundle_path / "logs.json"
    if logs_file.exists():
        with open(logs_file, "r", encoding="utf-8") as f:
            bundle["logs"] = json.load(f)

    # Metrics
    metrics_file = bundle_path / "metrics.json"
    if metrics_file.exists():
        with open(metrics_file, "r", encoding="utf-8") as f:
            bundle["metrics"] = json.load(f)

    # Changes
    changes_file = bundle_path / "changes.json"
    if changes_file.exists():
        with open(changes_file, "r", encoding="utf-8") as f:
            bundle["changes"] = json.load(f)

    # Service map
    service_map_file = bundle_path / "service_map.json"
    if service_map_file.exists():
        with open(service_map_file, "r", encoding="utf-8") as f:
            bundle["service_map"] = json.load(f)

    # Past incidents
    past_incidents_file = bundle_path / "past_incidents.json"
    if past_incidents_file.exists():
        with open(past_incidents_file, "r", encoding="utf-8") as f:
            bundle["past_incidents"] = json.load(f)

    # Repo snapshot / diff / files
    repo_file = bundle_path / "repo_snapshot.json"
    if repo_file.exists():
        with open(repo_file, "r", encoding="utf-8") as f:
            bundle["repo_snapshot"] = json.load(f)

    # Ground truth
    ground_truth_file = bundle_path / "ground_truth.json"
    if ground_truth_file.exists():
        with open(ground_truth_file, "r", encoding="utf-8") as f:
            bundle["ground_truth"] = json.load(f)
    else:
        # Check ground_truth.yaml if yaml library or raw text
        yaml_file = bundle_path / "ground_truth.yaml"
        if yaml_file.exists():
            bundle["ground_truth_raw"] = yaml_file.read_text(encoding="utf-8")

    return bundle
