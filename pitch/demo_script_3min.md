# NightShift — 3-Minute Live Demo Script with Timings (Day 10 Task B2)

**Total Rehearsal Duration:** `03:00` (`180 seconds`, strictly `<= 3:00`).

| Segment | Time Window | Duration | Speaker / Action |
| :--- | :---: | :---: | :--- |
| **1. Hook & Problem** | `0:00 – 0:25` | `25s` | Introduce NightShift: "At 3 AM, an unhandled deploy bug wakes up an engineer for ~10 minutes. NightShift resolves and verifies it in 7 seconds for 1.5 cents." |
| **2. Live Incident Injection & Auto-Resolution** | `0:25 – 1:15` | `50s` | Run `python run.py demo --fault fault_001_bad_deploy` while showing Live Dashboard (`http://127.0.0.1:8050`). Point out Timeline (`Detected -> Resolved`), red `FAULT` spike (22%) and green `FIX` recovery (0.2%). |
| **3. Clickable Trace & Evidence Grounding** | `1:15 – 1:45` | `30s` | Expand collapsible `query_logs` and `git_diff` tool calls in Agent Trace; click `ev_log_001` to open the exact raw stack trace line and PR #101 link. |
| **4. Live Safety Demo (T3, Rollback, Kill Switch)** | `1:45 – 2:30` | `45s` | Run `python -m pitch.safety_demo`: show (1) `T3` DB change held for human approval, (2) post-promotion degradation triggering auto-rollback, and (3) kill switch blocking all actions immediately. |
| **5. Measured Results & Business Case** | `2:30 – 3:00` | `30s` | Switch to `/results` 5-chart page: highlight `100%` Top-3 RCA, `80%` fix rate, `10/10` reliability, `5/5` unseen curveballs, `7.03s` vs `560s` human baseline, and `$0.0147` cost per incident. |

**Timed Rehearsal Check:** `25 + 50 + 30 + 45 + 30 = 180 seconds (3:00)`.
