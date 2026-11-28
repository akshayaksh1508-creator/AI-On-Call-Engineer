# NightShift — Day 12 Section 12 Final Submission Checklist (`B3`)

- **Verified (UTC):** 2026-11-26T15:20:54.894766+00:00
- **Score:** 14/14 ticked
- **Status:** ALL CHECKED

- [x] **1. Live demo works on a clean machine with one command** — `scripts/setup_clean_machine.{ps1,sh}, results/day12_env_freeze_checklist.json`
- [x] **2. Benchmark of 20 or more incidents with results.json and charts** — `results/final.json (total_runs=20), results/final_charts/ (5 files)`
- [x] **3. Held-out set reported separately** — `held_out_summary in results/final.json (total_runs=5)`
- [x] **4. Human baseline MTTR measured** — `results/human_baseline.json, results/human_baseline.md`
- [x] **5. At least 2 ablations** — `results/ablations/ (5 ablation files)`
- [x] **6. Failure analysis table** — `results/final_failure_table.md, results/final_failure_table.json`
- [x] **7. Safety tiers, auto-rollback and kill switch demonstrated** — `results/safety_demo_rehearsal.json, safety/gate.py`
- [x] **8. Cross-service incident demonstrated** — `fault_017_symptom_gw_cause_payments in results/final.json`
- [x] **9. Memory benefit measured** — `results/memory_experiment.json`
- [x] **10. Cost per incident computed** — `mean_cost_usd=$0.0159, total_cost_usd=$0.3180`
- [x] **11. Curveball prepared and rehearsed** — `results/curveball_results.json, results/day12_live_rehearsal.json`
- [x] **12. Backup video and offline fallback ready** — `results/demo_backup_video.{gif,webp,html}, results/recorded_replay_fault_001.json`
- [x] **13. Business case slide and Q&A prepared** — `pitch/deck_final.md, pitch/qa_bank.md`
- [x] **14. Every slide number matches results.json** — `pitch/cross_check.py (11 fields verified)`
