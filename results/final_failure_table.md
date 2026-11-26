# NightShift Final Failure Table (Matches `results/final.json`)

- **Total Runs:** 20
- **Passed (`fix_ok`):** 16
- **Total Failures:** 4

| Fault ID | Split | Flaky / Real | Triage Label | Cause | Proposed Change |
| :--- | :---: | :---: | :---: | :--- | :--- |
| `fault_008_broken_serialization` | training | `real` | `verify` | verify: missing sandbox reproduction harness for fault_008_broken_serialization | Implement sandbox reproducer and recovery metric check |
| `fault_013_conn_pool_exhaustion` | training | `real` | `RCA` | RCA: missing resource metric telemetry for fault_013_conn_pool_exhaustion | Enrich RCA prompt and platform log/metric evidence |
| `fault_014_memory_leak` | training | `real` | `RCA` | RCA: missing resource metric telemetry for fault_014_memory_leak | Enrich RCA prompt and platform log/metric evidence |
| `fault_016_slow_query_missing_index` | held_out | `real` | `fix` | fix: T3 DB index migration requires human approval | Add missing config/patch template for fault category |
