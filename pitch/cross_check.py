"""Two-Person Deck vs. results/final.json Cross-Check Validator (Day 11 Task B1).

Verifies programmatically that every locked number in `pitch/deck_final.md`
strictly matches `results/final.json`.

Owner: Person B (Brain & Trust)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Union

REPO_ROOT = Path(__file__).resolve().parent.parent


def cross_check_deck_against_final_json(
    *,
    deck_path: Union[str, Path] = REPO_ROOT / "pitch" / "deck_final.md",
    final_json_path: Union[str, Path] = REPO_ROOT / "results" / "final.json",
) -> Dict[str, Any]:
    """Check that all key metrics in deck_final.md match results/final.json."""
    deck_text = Path(deck_path).read_text(encoding="utf-8")
    final_data = json.loads(Path(final_json_path).read_text(encoding="utf-8"))

    s = final_data["summary"]
    ho = final_data["held_out_summary"]

    expected_tokens: Dict[str, str] = {
        "total_runs": f"**{s['total_runs']}**",
        "rca_top1_pct": f"{s['rca_top1_accuracy']:.1%}",
        "rca_top3_pct": f"{s['rca_top3_accuracy']:.1%}",
        "fix_success_pct": f"{s['fix_success_rate']:.1%}",
        "fix_ratio": f"`{s['fix_ok_count']}/{s['total_runs']}`",
        "unsafe_pct": f"{s['unsafe_rate']:.1%}",
        "median_total_time": f"{s['median_total_time']:.2f}s",
        "mean_total_time": f"{s['mean_total_time']:.2f}s",
        "mean_cost_usd": f"${s['mean_cost_usd']:.4f}",
        "total_cost_usd": f"${s['total_cost_usd']:.4f}",
        "held_out_fix_ratio": f"`{ho['fix_ok_count']}/{ho['total_runs']}`",
    }

    missing_or_mismatched: List[str] = [
        f"{k} (expected '{val}')"
        for k, val in expected_tokens.items()
        if val not in deck_text
    ]

    return {
        "passed": len(missing_or_mismatched) == 0,
        "checked_fields": list(expected_tokens.keys()),
        "mismatches": missing_or_mismatched,
    }
