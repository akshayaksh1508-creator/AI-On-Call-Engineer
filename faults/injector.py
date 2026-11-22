"""NightShift Fault Injector Framework.

Provides programmatic and CLI control to apply and revert known faults
against target microservices, with ground-truth manifests and change logging.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from faults.manifest import FaultManifest

CATALOG_DIR = Path(__file__).resolve().parent / "catalog"
DATA_DIR = REPO_ROOT / "data"
TARGET_APP_DIR = REPO_ROOT / "target-app"
ACTIVE_FAULT_FILE = DATA_DIR / "active_fault.json"
CHANGES_FILE = DATA_DIR / "changes.json"


class FaultInjector:
    """Manages injection, recovery, and status tracking for benchmark faults."""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def list_faults(self) -> List[Dict[str, Any]]:
        """Discover all faults registered in the catalog."""
        faults: List[Dict[str, Any]] = []
        if not CATALOG_DIR.exists():
            return faults

        for fault_dir in sorted(CATALOG_DIR.iterdir()):
            if fault_dir.is_dir():
                manifest_json = fault_dir / "manifest.json"
                manifest_yaml = fault_dir / "manifest.yaml"
                if manifest_json.exists():
                    try:
                        with open(manifest_json, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            faults.append(data)
                    except Exception:
                        pass
                elif manifest_yaml.exists():
                    try:
                        # Simple yaml parsing fallback
                        lines = manifest_yaml.read_text(encoding="utf-8").splitlines()
                        entry = {"fault_id": fault_dir.name}
                        for line in lines:
                            if ":" in line and not line.startswith(" ") and not line.startswith("-"):
                                k, v = line.split(":", 1)
                                entry[k.strip()] = v.strip().strip('"').strip("'")
                        faults.append(entry)
                    except Exception:
                        pass
        return faults

    def get_fault(self, fault_id: str) -> FaultManifest:
        """Retrieve the FaultManifest for a given fault ID."""
        fault_dir = CATALOG_DIR / fault_id
        if not fault_dir.exists():
            raise FileNotFoundError(f"Fault '{fault_id}' not found in {CATALOG_DIR}")

        manifest_json = fault_dir / "manifest.json"
        if manifest_json.exists():
            with open(manifest_json, "r", encoding="utf-8") as f:
                return FaultManifest(**json.load(f))

        manifest_yaml = fault_dir / "manifest.yaml"
        if manifest_yaml.exists():
            lines = manifest_yaml.read_text(encoding="utf-8").splitlines()
            entry: Dict[str, Any] = {"fault_id": fault_id}
            for line in lines:
                if ":" in line and not line.startswith(" ") and not line.startswith("-"):
                    k, v = line.split(":", 1)
                    entry[k.strip()] = v.strip().strip('"').strip("'")
            return FaultManifest(**entry)

        raise FileNotFoundError(f"No manifest found for fault '{fault_id}'")

    def status(self) -> Dict[str, Any]:
        """Check active fault status."""
        if ACTIVE_FAULT_FILE.exists():
            try:
                with open(ACTIVE_FAULT_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"active": False, "fault_id": None, "service": None, "version": "v1.0.0"}

    def _restart_service_if_docker(self, service_name: str) -> bool:
        """Restart container if docker is running nightshift containers."""
        try:
            container_name = f"nightshift-{service_name}"
            chk = subprocess.run(
                ["docker", "ps", "-q", "-f", f"name={container_name}"],
                capture_output=True,
                text=True,
                check=False,
            )
            if chk.returncode == 0 and chk.stdout.strip():
                subprocess.run(["docker", "restart", container_name], capture_output=True, check=False)
                return True
        except Exception:
            pass
        return False

    def _record_change(self, change_record: Dict[str, Any]) -> None:
        """Append deployment or rollback change event to data/changes.json."""
        changes: List[Dict[str, Any]] = []
        if CHANGES_FILE.exists():
            try:
                with open(CHANGES_FILE, "r", encoding="utf-8") as f:
                    changes = json.load(f)
            except Exception:
                changes = []

        changes.insert(0, change_record)
        with open(CHANGES_FILE, "w", encoding="utf-8") as f:
            json.dump(changes, f, indent=2)

    def apply(self, fault_id: str, record_change: bool = True) -> Dict[str, Any]:
        """Inject a fault into the target system."""
        manifest = self.get_fault(fault_id)
        fault_dir = CATALOG_DIR / fault_id

        if fault_id == "fault_001_bad_deploy":
            orders_app = TARGET_APP_DIR / "services" / "orders" / "app.py"
            backup_file = TARGET_APP_DIR / "services" / "orders" / "app.py.clean_bak"
            buggy_file = fault_dir / "buggy_app.py"

            if not buggy_file.exists():
                raise FileNotFoundError(f"Buggy app source not found at {buggy_file}")

            # Backup clean app if backup doesn't already exist
            if orders_app.exists() and not backup_file.exists():
                shutil.copyfile(orders_app, backup_file)

            # Apply faulty code
            shutil.copyfile(buggy_file, orders_app)

            # Update version to faulty version
            version_file = TARGET_APP_DIR / "version.txt"
            version_file.write_text(f"{manifest.faulty_version}\n", encoding="utf-8")

            # Record deploy change event
            ts_now = datetime.now(timezone.utc).isoformat()
            if record_change:
                change_entry = {
                    "id": manifest.culprit_change,
                    "service": manifest.target_service,
                    "timestamp": ts_now,
                    "version": manifest.faulty_version,
                    "git_commit": manifest.culprit_commit or "c0ffee14a",
                    "git_branch": "main",
                    "author": "dev-lead@nightshift.local",
                    "message": f"deploy({manifest.target_service}): {manifest.title}",
                    "config_diff": None,
                }
                self._record_change(change_entry)

            # Restart Docker container if running
            self._restart_service_if_docker(manifest.target_service)

            # Write active fault marker
            active_info = {
                "active": True,
                "fault_id": fault_id,
                "service": manifest.target_service,
                "version": manifest.faulty_version,
                "applied_at": ts_now,
                "root_cause": manifest.root_cause,
            }
            with open(ACTIVE_FAULT_FILE, "w", encoding="utf-8") as f:
                json.dump(active_info, f, indent=2)

            return {
                "status": "applied",
                "fault_id": fault_id,
                "service": manifest.target_service,
                "version": manifest.faulty_version,
                "message": f"Fault '{fault_id}' injected into {manifest.target_service}. Orders now throw 500 on unhandled None discount.",
            }
        else:
            raise NotImplementedError(f"Injection logic for fault '{fault_id}' not yet implemented.")

    def revert(self, fault_id: Optional[str] = None, record_change: bool = True) -> Dict[str, Any]:
        """Revert active fault and restore healthy baseline."""
        current_status = self.status()
        active_fault_id = fault_id or current_status.get("fault_id") or "fault_001_bad_deploy"

        fault_dir = CATALOG_DIR / active_fault_id
        clean_file = fault_dir / "clean_app.py"

        orders_app = TARGET_APP_DIR / "services" / "orders" / "app.py"
        backup_file = TARGET_APP_DIR / "services" / "orders" / "app.py.clean_bak"

        # Restore from backup or clean file
        if backup_file.exists():
            shutil.copyfile(backup_file, orders_app)
            try:
                backup_file.unlink()
            except Exception:
                pass
        elif clean_file.exists():
            shutil.copyfile(clean_file, orders_app)

        # Restore version to v1.0.0
        version_file = TARGET_APP_DIR / "version.txt"
        version_file.write_text("v1.0.0\n", encoding="utf-8")

        # Record rollback change event
        ts_now = datetime.now(timezone.utc).isoformat()
        if record_change:
            change_entry = {
                "id": f"rollback_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                "service": "orders",
                "timestamp": ts_now,
                "version": "v1.0.0",
                "git_commit": "a1b2c3d4e",
                "git_branch": "main",
                "author": "on-call@nightshift.local",
                "message": f"rollback(orders): revert {active_fault_id} back to v1.0.0 baseline",
                "config_diff": None,
            }
            self._record_change(change_entry)

        # Restart Docker container if running
        self._restart_service_if_docker("orders")

        # Clear active fault marker
        inactive_info = {
            "active": False,
            "fault_id": None,
            "service": None,
            "version": "v1.0.0",
            "reverted_at": ts_now,
        }
        with open(ACTIVE_FAULT_FILE, "w", encoding="utf-8") as f:
            json.dump(inactive_info, f, indent=2)

        return {
            "status": "reverted",
            "fault_id": active_fault_id,
            "service": "orders",
            "version": "v1.0.0",
            "message": f"Fault '{active_fault_id}' reverted. Orders service restored to clean v1.0.0 baseline.",
        }

    def patch(self, fault_id: str = "fault_001_bad_deploy", record_change: bool = True) -> Dict[str, Any]:
        """Apply the defensive code patch for verification."""
        fault_dir = CATALOG_DIR / fault_id
        patched_file = fault_dir / "patched_app.py"
        orders_app = TARGET_APP_DIR / "services" / "orders" / "app.py"

        if not patched_file.exists():
            raise FileNotFoundError(f"Patched app file not found at {patched_file}")

        shutil.copyfile(patched_file, orders_app)

        version_file = TARGET_APP_DIR / "version.txt"
        version_file.write_text("v1.0.1-patched\n", encoding="utf-8")

        ts_now = datetime.now(timezone.utc).isoformat()
        if record_change:
            change_entry = {
                "id": f"patch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                "service": "orders",
                "timestamp": ts_now,
                "version": "v1.0.1-patched",
                "git_commit": "f1x0001",
                "git_branch": "patch/orders-discount-check",
                "author": "agent@nightshift.local",
                "message": "fix(orders): add defensive null check for optional discount payload",
                "config_diff": None,
            }
            self._record_change(change_entry)

        self._restart_service_if_docker("orders")

        return {
            "status": "patched",
            "fault_id": fault_id,
            "service": "orders",
            "version": "v1.0.1-patched",
            "message": "Patch applied successfully. Defensive discount check is active.",
        }


# Global injector instance
injector = FaultInjector()
