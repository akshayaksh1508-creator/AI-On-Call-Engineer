"""Config / feature-flag faults 6-10 (Day 3, A3).

Faults are applied as realistic *config changes*: a docker-compose override file sets
environment variables on the culprit service and the service is recreated.
Each apply/revert emits a `config` change event (neutral message, real env diff),
exactly like a bad config push would in production.

Does not replace your Day 2 injector; it registers its own specs from faults/specs/.
Requires: pip install pyyaml
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from deployer.changes import ChangeLog
from deployer.runners import Runner

REQUIRED = ("id", "name", "category", "culprit_service", "symptom_service", "root_cause", "env", "expected_fix", "keywords")


@dataclass
class FaultSpec:
    id: str
    name: str
    category: str
    culprit_service: str
    symptom_service: str
    root_cause: str
    env: dict[str, dict[str, Any]]
    expected_fix: dict[str, Any]
    keywords: list[str]
    difficulty: str = "medium"
    cross_service: bool = False
    change_description: str = "Update service configuration"
    author: str = "deploy-bot"
    symptoms: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FaultSpec":
        missing = [k for k in REQUIRED if k not in data]
        if missing:
            raise ValueError(f"fault spec {data.get('id', '?')} missing keys: {missing}")
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


def load_specs(specs_dir: str | Path) -> dict[str, FaultSpec]:
    specs: dict[str, FaultSpec] = {}
    for p in sorted(Path(specs_dir).glob("*.y*ml")):
        spec = FaultSpec.from_dict(yaml.safe_load(p.read_text(encoding="utf-8")))
        specs[spec.id] = spec
    return specs


class EnvFaultInjector:
    def __init__(
        self,
        specs_dir: str | Path,
        runner: Runner,
        compose_file: str,
        override_path: str | Path,
        state_path: str | Path,
        changelog: ChangeLog | None = None,
    ):
        self.specs = load_specs(specs_dir)
        self.runner = runner
        self.compose_file = compose_file
        self.override_path = Path(override_path)
        self.state_path = Path(state_path)
        self.changelog = changelog
        self.override_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    # ---------- state ----------
    def active(self) -> list[str]:
        if not self.state_path.exists():
            return []
        return json.loads(self.state_path.read_text() or "{}").get("active", [])

    def _save_active(self, ids: list[str]) -> None:
        self.state_path.write_text(json.dumps({"active": ids}))

    def _write_override(self, ids: list[str]) -> None:
        services: dict[str, dict[str, Any]] = {}
        for fid in ids:
            for svc, env in self.specs[fid].env.items():
                services.setdefault(svc, {"environment": {}})["environment"].update(
                    {k: str(v) for k, v in env.items()}
                )
        self.override_path.write_text(yaml.safe_dump({"services": services}, sort_keys=True))

    def _get(self, fault_id: str) -> FaultSpec:
        if fault_id not in self.specs:
            raise KeyError(f"unknown fault {fault_id!r}; known: {sorted(self.specs)}")
        return self.specs[fault_id]

    # ---------- operations ----------
    def apply(self, fault_id: str) -> dict[str, Any]:
        spec = self._get(fault_id)
        ids = self.active()
        if fault_id in ids:
            return {"fault": fault_id, "changed": False}
        ids.append(fault_id)
        self._write_override(ids)
        self._save_active(ids)
        services = list(spec.env)
        self.runner.recreate(services, [self.compose_file, str(self.override_path)])
        if self.changelog:
            for svc, env in spec.env.items():
                self.changelog.emit(
                    "config", svc, None, None, spec.author, spec.change_description,
                    meta={"env": {k: {"to": str(v)} for k, v in env.items()}},
                )
        return {"fault": fault_id, "changed": True, "services": services}

    def revert(self, fault_id: str) -> dict[str, Any]:
        spec = self._get(fault_id)
        ids = self.active()
        if fault_id not in ids:
            return {"fault": fault_id, "changed": False}
        ids.remove(fault_id)
        self._write_override(ids)
        self._save_active(ids)
        services = list(spec.env)
        self.runner.recreate(services, [self.compose_file, str(self.override_path)])
        if self.changelog:
            for svc, env in spec.env.items():
                self.changelog.emit(
                    "config", svc, None, None, spec.author, "Revert configuration change",
                    meta={"env": {k: {"to": None} for k in env}},
                )
        return {"fault": fault_id, "changed": True, "services": services}

    def revert_all(self) -> list[str]:
        done = []
        for fid in list(self.active()):
            self.revert(fid)
            done.append(fid)
        return done

    def ground_truth(self, fault_id: str) -> dict[str, Any]:
        s = self._get(fault_id)
        return {
            "id": s.id, "category": s.category, "culprit_service": s.culprit_service,
            "symptom_service": s.symptom_service, "root_cause": s.root_cause,
            "expected_fix": s.expected_fix, "keywords": s.keywords,
        }
