# NightShift Human Baseline Timer Sheet (Day 9 Task A2)

- **Total Timed Runs:** 10 (Person A: 5, Person B: 5)
- **Mean Human Resolution Time:** 574.5s (9.6 min)
- **Median Human Resolution Time:** 560.0s (9.3 min)
- **Human Success Rate:** 100.0%
- **Blind Protocol Enforced (No Ground Truth Seen):** `True`

| Engineer | Fault ID | Start | End | Duration (s) | Tools | Notes |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- |
| Person A | `fault_001_bad_deploy` | `2026-11-25T10:00:00Z` | `2026-11-25T10:07:15Z` | 435 | dashboards, logs, git | Spotted 500 spike on orders dashboard; traced TypeError on discount['code'] via logs and git log. |
| Person A | `fault_002_off_by_one` | `2026-11-25T10:15:00Z` | `2026-11-25T10:24:30Z` | 570 | logs, git | Checked git diff on paginate_records; fixed 0-based page offset off-by-one bug. |
| Person A | `fault_003_wrong_status_code` | `2026-11-25T10:30:00Z` | `2026-11-25T10:41:20Z` | 680 | dashboards, logs, git | Reconciliation mismatch between orders and payments; found HTTP 200 returned on DECLINED card. |
| Person A | `fault_004_bad_parsing` | `2026-11-25T10:45:00Z` | `2026-11-25T10:53:40Z` | 520 | logs, git | Gateway ValueError on ISO-8601 Z suffix in Python 3.11; normalized Z to +00:00. |
| Person A | `fault_005_unhandled_exception` | `2026-11-25T11:00:00Z` | `2026-11-25T11:09:10Z` | 550 | dashboards, logs, git | Caught ZeroDivisionError in calculate_unit_discount when quantity == 0. |
| Person B | `fault_001_bad_deploy` | `2026-11-25T11:15:00Z` | `2026-11-25T11:23:00Z` | 480 | dashboards, logs, git | Identified NoneType subscript crash in orders checkout logs; patched with dict guard. |
| Person B | `fault_002_off_by_one` | `2026-11-25T11:28:00Z` | `2026-11-25T11:39:15Z` | 675 | logs, git | Inspected recent git commits on orders; corrected pagination slice start index. |
| Person B | `fault_003_wrong_status_code` | `2026-11-25T11:45:00Z` | `2026-11-25T11:57:30Z` | 750 | dashboards, logs, git | Zero 5xx on payments dashboard despite failed orders; traced DECLINED response returning 200. |
| Person B | `fault_004_bad_parsing` | `2026-11-25T12:00:00Z` | `2026-11-25T12:08:20Z` | 500 | logs, git | Found timestamp parse failure on trailing Z in gateway logs; updated parser. |
| Person B | `fault_005_unhandled_exception` | `2026-11-25T12:12:00Z` | `2026-11-25T12:21:45Z` | 585 | dashboards, logs, git | Traced unhandled ZeroDivisionError on zero-quantity order discount calculation. |
