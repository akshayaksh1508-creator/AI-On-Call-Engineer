# NightShift — Day 12 Pitch Rehearsal Log (`B1`)

- **Target Pitch Window:** `<= 180s` (3:00 minutes)
- **Fallback Switch SLA:** `< 20s` from forced failure detection to offline replay / backup video playback
- **Final Rule:** No merges after the last rehearsal; if anything breaks live, switch to the offline fallback immediately.

---

## Three Full Pitch Rehearsals

| Rehearsal | Mode | Total Time (s) | Within 180s Cap | Forced Failure Injected | Fallback Switch Time (s) | Fallback SLA (< 20s) | Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Run 1** | Standard Live Demo | `168s` (`2m 48s`) | Yes | None | `N/A` | `N/A` | **PASS** — clean recovery + dashboard trace |
| **Run 2** | Forced Failure -> Offline Replay | `174s` (`2m 54s`) | Yes | Simulated network drop / API timeout during live RCA | `11s` | Yes (`11s < 20s`) | **PASS** — switched via `python -m bench.offline_replay` + live dashboard |
| **Run 3** | Forced Failure -> Backup Video + Solo Backup | `171s` (`2m 51s`) | Yes | Simulated container health stall before canary | `8s` | Yes (`8s < 20s`) | **PASS** — switched to `results/demo_backup_video.html` + `pitch/deck_final.md` |

---

## Fallback Trigger & 20-Second Switch Procedure
1. **Trigger:** Any live command stalls `> 8s` or returns non-zero exit during the 60s–135s demo window.
2. **Switch Step 1 (`0–5s`):** Presenter B continues narrating the RCA & Safety Gate slide seamlessly without pausing.
3. **Switch Step 2 (`5–11s`):** Operator A runs `python -m bench.offline_replay` (or opens `results/demo_backup_video.html` already pre-loaded in Browser Tab 2).
4. **Verification:** Total transition completed in `8s–11s` across Runs 2 and 3, keeping full pitch within `180s`.
