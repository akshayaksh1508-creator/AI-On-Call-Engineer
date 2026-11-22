"""Fault Injection Manifest Schema and Models.

Defines the structure for faults, catalog entries, and ground truth definitions.
"""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


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
    culprit_change: str = Field(..., description="Identifier of deploy or config change, e.g. dep_20261122_v1.0.1")
    culprit_commit: Optional[str] = Field(default=None, description="Culprit commit hash or ref")
    root_cause: str = Field(..., description="Detailed ground-truth explanation of root cause mechanism")
    visible_symptoms: List[str] = Field(
        default_factory=list, description="Observable symptoms in logs and metrics"
    )
    expected_fix_type: Literal["patch", "rollback", "config"] = "patch"
    alternative_fix_type: Optional[Literal["patch", "rollback", "config"]] = "rollback"
    risk_tier: Literal["T0", "T1", "T2", "T3"] = "T2"
    suggested_patch: Optional[str] = Field(
        default=None, description="Suggested unified diff or code fix snippet"
    )
    rollback_version: Optional[str] = Field(
        default="v1.0.0", description="Clean baseline version tag"
    )
    faulty_version: Optional[str] = Field(
        default="v1.0.1", description="Faulty deployed version tag"
    )
