"""Export Pydantic models to JSON Schema files.

Outputs standard JSON Schemas to contracts/schemas/*.json.
"""

import sys
import json
from pathlib import Path
from typing import Dict, Type

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import BaseModel
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

CORE_MODELS: Dict[str, Type[BaseModel]] = {
    "Incident": Incident,
    "Evidence": Evidence,
    "Hypothesis": Hypothesis,
    "FixProposal": FixProposal,
    "VerificationResult": VerificationResult,
    "RunRecord": RunRecord,
    "ChangeRecord": ChangeRecord,
    "CommitRecord": CommitRecord,
    "ServiceNode": ServiceNode,
    "ServiceMap": ServiceMap,
    "FixProposalReceipt": FixProposalReceipt,
}


def export_all_schemas(output_dir: Path = None) -> Dict[str, Path]:
    """Generates JSON schema files for all core models."""
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent / "schemas"

    output_dir.mkdir(parents=True, exist_ok=True)
    exported: Dict[str, Path] = {}

    for name, model_cls in CORE_MODELS.items():
        schema = model_cls.model_json_schema()
        schema_path = output_dir / f"{name}.json"
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)
        exported[name] = schema_path

    return exported


if __name__ == "__main__":
    out = export_all_schemas()
    print(f"Exported {len(out)} JSON schemas:")
    for name, p in out.items():
        print(f"  - {name} -> {p.name}")
