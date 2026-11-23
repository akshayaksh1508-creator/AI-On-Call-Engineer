"""Fault Injection Manifest Schema and Models.

Defines the structure for faults, catalog entries, and ground truth definitions.
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FaultManifest(BaseModel):
    """Metadata and ground-truth specification for an injected fault."""
    model_config = ConfigDict(extra="ignore")

    fault_id: str = Field(..., description="Unique fault identifier, e.g. fault_001_bad_deploy")
    title: str = Field(..., description="Short title describing the failure scenario")
    category: Literal["code", "config", "resource", "cross_service", "dependency", "stretch"] = Field(
        ..., description="Fault classification category"
    )
    difficulty: Literal["easy", "medium", "hard"] = "easy"
    target_service: str = Field(..., description="Service primary impacted, e.g. orders")
    target_file: Optional[str] = Field(
        default=None, description="Path relative to repo root of the file modified"
    )
    culprit_change: str = Field(..., description="Identifier of deploy or config change, e.g. dep_20261122_v1.0.1")
    culprit_commit: Optional[str] = Field(default=None, description="Culprit commit hash or ref")
    root_cause: str = Field(..., description="Detailed ground-truth explanation of root cause mechanism")
    visible_symptoms: List[str] = Field(
        default_factory=list, description="Observable symptoms in logs and metrics"
    )
    visible_symptom: Optional[str] = Field(
        default=None, description="Primary observable symptom string"
    )
    expected_fix: Optional[str] = Field(
        default=None, description="Human readable description of expected fix"
    )
    expected_fix_type: Literal["patch", "rollback", "config"] = "patch"
    alternative_fix_type: Optional[Literal["patch", "rollback", "config"]] = "rollback"
    risk_tier: Literal["T0", "T1", "T2", "T3"] = "T2"
    suggested_patch: Optional[str] = Field(
        default=None, description="Suggested unified diff or code fix snippet"
    )
    diff: Optional[str] = Field(
        default=None, description="Unified diff of fault change"
    )
    rollback_version: Optional[str] = Field(
        default="v1.0.0", description="Clean baseline version tag"
    )
    faulty_version: Optional[str] = Field(
        default="v1.0.1", description="Faulty deployed version tag"
    )

    @model_validator(mode="before")
    @classmethod
    def populate_aliases(cls, values: Any) -> Any:
        if isinstance(values, dict):
            # Support id alias for fault_id
            if "fault_id" not in values and "id" in values:
                values["fault_id"] = values["id"]
            if "id" not in values and "fault_id" in values:
                values["id"] = values["fault_id"]
            # Support service alias for target_service
            if "target_service" not in values and "service" in values:
                values["target_service"] = values["service"]
            # Support visible_symptom <-> visible_symptoms
            if "visible_symptoms" not in values and "visible_symptom" in values:
                values["visible_symptoms"] = [values["visible_symptom"]]
            elif "visible_symptom" not in values and values.get("visible_symptoms"):
                values["visible_symptom"] = values["visible_symptoms"][0]
            # Support diff <-> suggested_patch
            if "suggested_patch" not in values and "diff" in values:
                values["suggested_patch"] = values["diff"]
            elif "diff" not in values and "suggested_patch" in values:
                values["diff"] = values["suggested_patch"]
            # Title fallback if missing
            if "title" not in values:
                values["title"] = values.get("root_cause", values.get("fault_id", "Injected Fault"))
        return values
