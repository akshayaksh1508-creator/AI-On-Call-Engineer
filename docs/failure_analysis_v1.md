# NightShift Benchmark v1 — Draft Failure-Analysis Table

| Incident | Label | Cause of Failure | Proposed Change |
| :--- | :--- | :--- | :--- |
| `inc_v1_fault_006_wrong_timeout_value (fault_006_wrong_timeout_value)` | `verify` | verify: missing sandbox reproduction harness for fault_006_wrong_timeout_value | Implement sandbox reproducer and recovery metric check |
| `inc_v1_fault_007_bad_sql_query (fault_007_bad_sql_query)` | `verify` | verify: missing sandbox reproduction harness for fault_007_bad_sql_query | Implement sandbox reproducer and recovery metric check |
| `inc_v1_fault_008_broken_serialization (fault_008_broken_serialization)` | `verify` | verify: missing sandbox reproduction harness for fault_008_broken_serialization | Implement sandbox reproducer and recovery metric check |
| `inc_v1_fault_011_wrong_pool_size (fault_011_wrong_pool_size)` | `fix` | fix: T1 config revert missing override mapping for fault_011_wrong_pool_size | Add missing config/patch template for fault category |
| `inc_v1_fault_012_bad_feature_flag (fault_012_bad_feature_flag)` | `fix` | fix: T1 config revert missing override mapping for fault_012_bad_feature_flag | Add missing config/patch template for fault category |
| `inc_v1_fault_013_conn_pool_exhaustion (fault_013_conn_pool_exhaustion)` | `RCA` | RCA: missing resource metric telemetry for fault_013_conn_pool_exhaustion | Enrich RCA prompt and platform log/metric evidence |
| `inc_v1_fault_014_memory_leak (fault_014_memory_leak)` | `RCA` | RCA: missing resource metric telemetry for fault_014_memory_leak | Enrich RCA prompt and platform log/metric evidence |
| `inc_v1_fault_015_disk_full (fault_015_disk_full)` | `verify` | verify: resource recovery check unimplemented for fault_015_disk_full | Implement sandbox reproducer and recovery metric check |
