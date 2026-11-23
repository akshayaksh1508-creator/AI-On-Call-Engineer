"""NightShift Fault Injector Framework.

Provides programmatic and CLI control to apply and revert known faults
against target microservices, with ground-truth manifests and change logging.
"""

import argparse
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

    def get_ground_truth(self, fault_id: str) -> Dict[str, Any]:
        """Retrieve ground-truth YAML manifest for evaluation."""
        fault_dir = CATALOG_DIR / fault_id
        gt_file = fault_dir / "ground_truth.yaml"
        if not gt_file.exists():
            gt_file = REPO_ROOT / "faults" / "fixtures" / fault_id / "ground_truth.yaml"

        if gt_file.exists():
            lines = gt_file.read_text(encoding="utf-8").splitlines()
            data: Dict[str, Any] = {}
            in_multiline: Optional[str] = None
            multiline_lines: List[str] = []
            in_list: Optional[str] = None
            list_items: List[str] = []

            for line in lines:
                if in_multiline:
                    if line.startswith("  ") or line.startswith("\t") or line == "":
                        multiline_lines.append(line[2:] if line.startswith("  ") else line)
                        continue
                    else:
                        data[in_multiline] = "\n".join(multiline_lines)
                        in_multiline = None
                        multiline_lines = []

                if in_list:
                    stripped = line.strip()
                    if stripped.startswith("- "):
                        list_items.append(stripped[2:].strip().strip('"').strip("'"))
                        continue
                    else:
                        data[in_list] = list_items
                        in_list = None
                        list_items = []

                if ":" in line and not line.startswith(" "):
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    if v == "|":
                        in_multiline = k
                        multiline_lines = []
                    elif v == "" or v == "[]":
                        in_list = k
                        list_items = []
                    else:
                        data[k] = v.strip('"').strip("'")

            if in_multiline:
                data[in_multiline] = "\n".join(multiline_lines)
            if in_list:
                data[in_list] = list_items

            if "id" not in data and "fault_id" in data:
                data["id"] = data["fault_id"]
            if "target_service" not in data and "service" in data:
                data["target_service"] = data["service"]
            if "diff" not in data and "suggested_patch" in data:
                data["diff"] = data["suggested_patch"]
            return data

        manifest = self.get_fault(fault_id)
        return manifest.model_dump()

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

    def _get_target_path(self, manifest: FaultManifest) -> Path:
        """Resolve the target file to modify for a given fault."""
        if manifest.target_file:
            target = REPO_ROOT / manifest.target_file
            if target.exists() or target.parent.exists():
                return target
        return TARGET_APP_DIR / "services" / manifest.target_service / "app.py"

    def apply(self, fault_id: str, record_change: bool = True) -> Dict[str, Any]:
        """Inject a fault into the target system."""
        manifest = self.get_fault(fault_id)
        fault_dir = CATALOG_DIR / fault_id
        target_path = self._get_target_path(manifest)
        backup_file = target_path.with_name(f"{target_path.name}.clean_bak")

        # Find buggy implementation file
        buggy_file = fault_dir / "buggy_app.py"
        if not buggy_file.exists():
            buggy_file = fault_dir / f"buggy_{target_path.name}"
        if not buggy_file.exists():
            raise FileNotFoundError(f"Buggy source not found for fault '{fault_id}' in {fault_dir}")

        # Backup clean app if backup doesn't already exist
        if target_path.exists() and not backup_file.exists():
            shutil.copyfile(target_path, backup_file)

        # Apply faulty code
        shutil.copyfile(buggy_file, target_path)

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
            "target_file": str(target_path.relative_to(REPO_ROOT)),
        }
        with open(ACTIVE_FAULT_FILE, "w", encoding="utf-8") as f:
            json.dump(active_info, f, indent=2)

        return {
            "status": "applied",
            "fault_id": fault_id,
            "service": manifest.target_service,
            "version": manifest.faulty_version,
            "message": f"Fault '{fault_id}' injected into {manifest.target_service} ({manifest.title}).",
        }

    def revert(self, fault_id: Optional[str] = None, record_change: bool = True) -> Dict[str, Any]:
        """Revert active fault and restore healthy baseline across all services."""
        current_status = self.status()
        active_fault_id = fault_id or current_status.get("fault_id")
        target_service = current_status.get("service") or "orders"

        # 1. Restore specific active fault clean file if known
        if active_fault_id:
            try:
                manifest = self.get_fault(active_fault_id)
                target_service = manifest.target_service
                clean_file = CATALOG_DIR / active_fault_id / "clean_app.py"
                target_path = self._get_target_path(manifest)
                if clean_file.exists():
                    shutil.copyfile(clean_file, target_path)
            except Exception:
                pass

        # 2. Check and clean up any remaining backups across all services
        for svc_name in ["orders", "payments", "gateway"]:
            svc_dir = TARGET_APP_DIR / "services" / svc_name
            if svc_dir.is_dir():
                for bak in svc_dir.glob("*.clean_bak"):
                    orig = bak.with_name(bak.name.replace(".clean_bak", ""))
                    shutil.copyfile(bak, orig)
                    try:
                        bak.unlink()
                    except Exception:
                        pass

        # 3. Ensure all three services are at clean baseline
        orders_clean = CATALOG_DIR / "fault_001_bad_deploy" / "clean_app.py"
        if orders_clean.exists():
            shutil.copyfile(orders_clean, TARGET_APP_DIR / "services" / "orders" / "app.py")

        payments_clean = CATALOG_DIR / "fault_003_wrong_status_code" / "clean_app.py"
        if payments_clean.exists():
            shutil.copyfile(payments_clean, TARGET_APP_DIR / "services" / "payments" / "app.py")

        gateway_clean = CATALOG_DIR / "fault_004_bad_parsing" / "clean_app.py"
        if gateway_clean.exists():
            shutil.copyfile(gateway_clean, TARGET_APP_DIR / "services" / "gateway" / "app.py")

        # Restore version to v1.0.0
        version_file = TARGET_APP_DIR / "version.txt"
        version_file.write_text("v1.0.0\n", encoding="utf-8")

        # Record rollback change event
        ts_now = datetime.now(timezone.utc).isoformat()
        if record_change:
            change_entry = {
                "id": f"rollback_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                "service": target_service,
                "timestamp": ts_now,
                "version": "v1.0.0",
                "git_commit": "a1b2c3d4e",
                "git_branch": "main",
                "author": "on-call@nightshift.local",
                "message": f"rollback({target_service}): revert {active_fault_id or 'active fault'} back to v1.0.0 baseline",
                "config_diff": None,
            }
            self._record_change(change_entry)

        # Restart Docker container if running
        self._restart_service_if_docker(target_service)

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
            "service": target_service,
            "version": "v1.0.0",
            "message": f"Fault '{active_fault_id}' reverted. System restored to clean v1.0.0 baseline.",
        }

    def patch(self, fault_id: Optional[str] = None, record_change: bool = True) -> Dict[str, Any]:
        """Apply the defensive code patch for verification."""
        current_status = self.status()
        active_fault_id = fault_id or current_status.get("fault_id") or "fault_001_bad_deploy"

        manifest = self.get_fault(active_fault_id)
        fault_dir = CATALOG_DIR / active_fault_id
        target_path = self._get_target_path(manifest)

        patched_file = fault_dir / "patched_app.py"
        if not patched_file.exists():
            patched_file = fault_dir / f"patched_{target_path.name}"
        if not patched_file.exists():
            raise FileNotFoundError(f"Patched app file not found at {patched_file}")

        # Ensure backup of clean file before patching if not already backed up
        backup_file = target_path.with_name(f"{target_path.name}.clean_bak")
        if target_path.exists() and not backup_file.exists():
            shutil.copyfile(target_path, backup_file)

        shutil.copyfile(patched_file, target_path)

        version_file = TARGET_APP_DIR / "version.txt"
        version_file.write_text(f"{manifest.faulty_version}-patched\n", encoding="utf-8")

        ts_now = datetime.now(timezone.utc).isoformat()
        if record_change:
            change_entry = {
                "id": f"patch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
                "service": manifest.target_service,
                "timestamp": ts_now,
                "version": f"{manifest.faulty_version}-patched",
                "git_commit": f"f1x_{active_fault_id[:7]}",
                "git_branch": f"patch/{active_fault_id}",
                "author": "agent@nightshift.local",
                "message": f"fix({manifest.target_service}): {manifest.expected_fix or manifest.title}",
                "config_diff": None,
            }
            self._record_change(change_entry)

        self._restart_service_if_docker(manifest.target_service)

        active_info = {
            "active": True,
            "fault_id": active_fault_id,
            "service": manifest.target_service,
            "version": f"{manifest.faulty_version}-patched",
            "applied_at": ts_now,
            "status": "patched",
            "target_file": str(target_path.relative_to(REPO_ROOT)),
        }
        with open(ACTIVE_FAULT_FILE, "w", encoding="utf-8") as f:
            json.dump(active_info, f, indent=2)

        return {
            "status": "patched",
            "fault_id": active_fault_id,
            "service": manifest.target_service,
            "version": f"{manifest.faulty_version}-patched",
            "message": f"Patch applied successfully for '{active_fault_id}'. Defensive remediation active.",
        }


# Global injector instance
injector = FaultInjector()


def main():
    parser = argparse.ArgumentParser(description="NightShift Fault Injector CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    subparsers.add_parser("list", help="List registered catalog faults")
    subparsers.add_parser("status", help="Show current fault injection status")

    apply_p = subparsers.add_parser("apply", help="Apply a fault")
    apply_p.add_argument("fault_id", help="Fault identifier (e.g. fault_001_bad_deploy)")

    revert_p = subparsers.add_parser("revert", help="Revert a fault")
    revert_p.add_argument("fault_id", nargs="?", default=None, help="Optional fault ID to revert")

    patch_p = subparsers.add_parser("patch", help="Apply code patch")
    patch_p.add_argument("fault_id", nargs="?", default=None, help="Optional fault ID to patch")

    args = parser.parse_args()
    if args.command == "list":
        faults = injector.list_faults()
        print(f"Discovered {len(faults)} faults:")
        for f in faults:
            print(f" - {f.get('fault_id')}: {f.get('title')} [{f.get('target_service')}]")
    elif args.command == "status":
        st = injector.status()
        print(json.dumps(st, indent=2))
    elif args.command == "apply":
        res = injector.apply(args.fault_id)
        print(json.dumps(res, indent=2))
    elif args.command == "revert":
        res = injector.revert(args.fault_id)
        print(json.dumps(res, indent=2))
    elif args.command == "patch":
        res = injector.patch(args.fault_id)
        print(json.dumps(res, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
