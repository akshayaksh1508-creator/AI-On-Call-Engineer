# NightShift — Day 12 Demo Choreography Run-Sheet (`B2`)

> **Design Goal:** Zero dead air during the 3-minute pitch, clean handoffs between **Person A** and **Person B**, and full **solo-capable** instructions so either teammate can run the entire demo alone if needed.

---

## Role Matrix

| Segment | Time | Who Types (Terminal / UI) | Who Speaks | Who Handles Judge Curveball |
| :--- | :--- | :--- | :--- | :--- |
| **1. Hook & Problem** (Slides 1–2) | `0:00 – 0:30` | Person A (pre-stages terminal & dashboard tabs) | Person B | — |
| **2. Architecture & Safety Gate** (Slide 3) | `0:30 – 0:55` | Person A (triggers `python run.py demo --fault 1`) | Person B | — |
| **3. Live Demo & Dashboard Trace** | `0:55 – 1:50` | Person A (shows terminal recovery + `python -m dashboard` trace) | Person B (narrates RCA, T1 rollback, canary verification) | Person A stands by on `results/demo_backup_video.html` Tab 2 (`< 20s` fallback) |
| **4. Benchmark & Failure Analysis** (Slides 4–6) | `1:50 – 2:30` | Person A (advances slides & `results/final_results_page.html`) | Person B (`N=20`, `100%` Top-1 RCA, `80%` Fix, `0%` Unsafe, `7.03s` MTTR) | — |
| **5. Business Case & Close** (Slides 7–9) | `2:30 – 3:00` | Person A | Person B | — |
| **6. Judge Curveball & Q&A** | `3:00+` | **Person A** (injects judge-requested fault ID or runs `python -m bench.offline_replay`) | **Person B** (answers via `pitch/qa_bank.md` in `< 30s`) | **Joint:** Person A drives CLI/proof; Person B owns verbal framing & safety explanation |

---

## Solo Fallback Mode (Both People Can Run It Alone)
- **If Person A runs solo:**
  1. Keep `pitch/deck_final.md` and `results/demo_backup_video.html` open in adjacent browser tabs.
  2. Run `python run.py demo --fault 1` in terminal while reading the condensed cues in `pitch/demo_script_3min.md`.
  3. Answer Q&A directly from `pitch/qa_bank.md`.
- **If Person B runs solo:**
  1. Pre-open two terminal panes: Pane 1 (`python -m dashboard`), Pane 2 (`python run.py demo --fault 1` pre-typed).
  2. Use `results/demo_backup_video.html` in Tab 2 if Pane 2 stalls `> 8s`.
  3. Handle both narration and judge curveball command (`python -m bench.day12_live_rehearsal`) from the pre-typed history buffer.
