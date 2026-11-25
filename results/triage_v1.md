# Benchmark v1 Failure Triage Sheet

- **Total Runs:** 15
- **Total Failures:** 8
- **Counts by Label:** `detect`: 0, `RCA`: 2, `fix`: 2, `verify`: 4, `infrastructure`: 0

| Fault ID | Label | One-Line Cause | Proposed Change |
| :--- | :--- | :--- | :--- |
| `fault_006_wrong_timeout_value` | `verify` | verify: missing sandbox reproduction harness for fault_006_wrong_timeout_value | Implement sandbox reproducer and recovery metric check |
| `fault_007_bad_sql_query` | `verify` | verify: missing sandbox reproduction harness for fault_007_bad_sql_query | Implement sandbox reproducer and recovery metric check |
| `fault_008_broken_serialization` | `verify` | verify: missing sandbox reproduction harness for fault_008_broken_serialization | Implement sandbox reproducer and recovery metric check |
| `fault_011_wrong_pool_size` | `fix` | fix: T1 config revert missing override mapping for fault_011_wrong_pool_size | Add missing config/patch template for fault category |
| `fault_012_bad_feature_flag` | `fix` | fix: T1 config revert missing override mapping for fault_012_bad_feature_flag | Add missing config/patch template for fault category |
| `fault_013_conn_pool_exhaustion` | `RCA` | RCA: missing resource metric telemetry for fault_013_conn_pool_exhaustion | Enrich RCA prompt and platform log/metric evidence |
| `fault_014_memory_leak` | `RCA` | RCA: missing resource metric telemetry for fault_014_memory_leak | Enrich RCA prompt and platform log/metric evidence |
| `fault_015_disk_full` | `verify` | verify: resource recovery check unimplemented for fault_015_disk_full | Implement sandbox reproducer and recovery metric check |
