import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.fault_01 import calculate_total
from src.fault_02 import normalize_status
from src.fault_03 import retry_delay
from src.fault_04 import parse_quantity
from src.fault_05 import is_success

checks = {
    "fault_01": lambda: calculate_total([10, 20, 30]) == 60,
    "fault_02": lambda: normalize_status(" PAID ") == "complete",
    "fault_03": lambda: retry_delay(3) == 8,
    "fault_04": lambda: parse_quantity({}) == 0,
    "fault_05": lambda: is_success(302) is True,
}
fault = sys.argv[1] if len(sys.argv) > 1 else ""
if fault not in checks:
    raise SystemExit("Usage: python scripts/reproduce.py fault_01|...|fault_05")
if not checks[fault]():
    raise SystemExit(f"REPRO_FAILED: {fault}")
print(f"REPRO_FIXED: {fault}")
