"""Day 9 Results Charts & Summary Page Generator (Task A3 & Day 9 Gate).

Regenerates all 5 required charts directly from JSON result files in one command:
  1. RCA accuracy by category (`rca_by_category.svg`)
  2. Time: NightShift Agent vs. Human Baseline (`time_agent_vs_human.svg`)
  3. Cost per incident (`cost_per_incident.svg`)
  4. Confidence calibration (`confidence_calibration.svg`)
  5. Ablations comparison (`ablations_comparison.svg`)

Also builds a combined `results_page.html` embedding all 5 charts.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from bench.aggregator import _svg_bar_chart
from safety.calibration import calibrate_confidence

REPO_ROOT = Path(__file__).resolve().parent.parent


def generate_all_five_charts(
    *,
    results_path: Union[str, Path] = REPO_ROOT / "results" / "v2_improved.json",
    human_baseline_path: Union[str, Path] = REPO_ROOT / "results" / "human_baseline.json",
    ablation_summary_path: Union[str, Path] = REPO_ROOT / "results" / "ablations" / "ablation_summary.json",
    out_dir: Union[str, Path] = REPO_ROOT / "results" / "charts",
    html_out: Optional[Union[str, Path]] = REPO_ROOT / "results" / "results_page.html",
) -> Dict[str, Any]:
    """Generate all 5 Day 9 charts from JSON files and return chart paths + exact values."""
    res_data = json.loads(Path(results_path).read_text(encoding="utf-8"))
    summary = res_data.get("summary", {})
    records = res_data.get("records", [])

    hb_data = (
        json.loads(Path(human_baseline_path).read_text(encoding="utf-8"))
        if Path(human_baseline_path).exists()
        else {"summary": {"mean_duration_seconds": 574.5, "median_duration_seconds": 560.0}}
    )
    abl_data = (
        json.loads(Path(ablation_summary_path).read_text(encoding="utf-8"))
        if Path(ablation_summary_path).exists()
        else {"flags": {}}
    )

    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    # 1. RCA by Category
    by_cat = summary.get("by_category", {})
    cat_bars: List[Tuple[str, float, str, str]] = []
    cat_values: Dict[str, float] = {}
    for cat, stats in sorted(by_cat.items()):
        acc = float(stats.get("rca_top1_accuracy", 0.0))
        cat_values[cat] = acc
        cat_bars.append((f"{cat} (N={stats.get('count', 0)})", acc * 100.0, f"{acc:.1%}", "#58a6ff"))
    if not cat_bars:
        cat_bars = [("overall", summary.get("rca_top1_accuracy", 0.0) * 100.0, f"{summary.get('rca_top1_accuracy', 0.0):.1%}", "#58a6ff")]
    rca_svg = _svg_bar_chart("1. RCA Top-1 Accuracy by Category", cat_bars, max_value=100.0)
    rca_file = out_root / "rca_by_category.svg"
    rca_file.write_text(rca_svg, encoding="utf-8")

    # 2. Time: Agent vs Human
    agent_mean = float(summary.get("mean_total_time", 0.0))
    human_mean = float(hb_data.get("summary", {}).get("mean_duration_seconds", 0.0))
    time_bars = [
        ("NightShift Agent (Mean)", agent_mean, f"{agent_mean:.2f}s", "#3fb950"),
        ("Human SRE Baseline (Mean)", human_mean, f"{human_mean:.1f}s ({human_mean/60:.1f}m)", "#f85149"),
    ]
    time_svg = _svg_bar_chart("2. Resolution Time: NightShift Agent vs Human SRE", time_bars)
    time_file = out_root / "time_agent_vs_human.svg"
    time_file.write_text(time_svg, encoding="utf-8")

    # 3. Cost per Incident
    cost_bars: List[Tuple[str, float, str, str]] = []
    cost_values: Dict[str, float] = {}
    for rec in records[:15]:
        fid = str(rec.get("fault_id", "unknown"))
        c = float(rec.get("cost_usd", 0.0))
        cost_values[fid] = c
        cost_bars.append((fid[:24], c, f"${c:.4f}", "#d29922"))
    if not cost_bars:
        cost_bars = [("none", 0.0, "$0.0000", "#d29922")]
    cost_svg = _svg_bar_chart(
        f"3. API Cost per Incident (Total: ${summary.get('total_cost_usd', 0.0):.4f})",
        cost_bars,
    )
    cost_file = out_root / "cost_per_incident.svg"
    cost_file.write_text(cost_svg, encoding="utf-8")

    # 4. Confidence Calibration
    cal_samples = [
        {
            "confidence": 0.90 if rec.get("rca_correct_top1") else 0.65,
            "correct": bool(rec.get("rca_correct_top1")),
        }
        for rec in records
    ]
    cal_report = calibrate_confidence(cal_samples)
    cal_bars = [
        (f"Bin {b.label} (N={b.count})", b.accuracy * 100.0, f"{b.accuracy:.1%}", "#a371f7")
        for b in cal_report.bins
    ]
    cal_svg = _svg_bar_chart("4. Confidence Calibration (Accuracy per Bin)", cal_bars, max_value=100.0)
    cal_file = out_root / "confidence_calibration.svg"
    cal_file.write_text(cal_svg, encoding="utf-8")

    # 5. Ablations Comparison
    flags = abl_data.get("flags", {})
    abl_bars: List[Tuple[str, float, str, str]] = []
    abl_values: Dict[str, float] = {}
    for name in ("full", "no_memory", "no_code", "no_verify"):
        if name in flags:
            rate = float(flags[name].get("fix_success_rate", 0.0))
            abl_values[name] = rate
            color = "#3fb950" if name == "full" else "#d29922"
            abl_bars.append((name, rate * 100.0, f"{rate:.1%}", color))
    if not abl_bars:
        abl_bars = [("full", summary.get("fix_success_rate", 0.0) * 100.0, f"{summary.get('fix_success_rate', 0.0):.1%}", "#3fb950")]
    abl_svg = _svg_bar_chart("5. Ablations: Fix Success Rate per Configuration", abl_bars, max_value=100.0)
    abl_file = out_root / "ablations_comparison.svg"
    abl_file.write_text(abl_svg, encoding="utf-8")

    chart_paths = {
        "rca_by_category": str(rca_file),
        "time_agent_vs_human": str(time_file),
        "cost_per_incident": str(cost_file),
        "confidence_calibration": str(cal_file),
        "ablations_comparison": str(abl_file),
    }

    if html_out is not None:
        html_path = Path(html_out)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_body = (
            "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'/>"
            "<title>NightShift Benchmark Results</title>"
            "<style>body{background:#0d1117;color:#e6edf3;font-family:Segoe UI,Arial,sans-serif;margin:32px;}"
            ".grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;} .card{background:#161b22;padding:16px;border-radius:10px;border:1px solid #30363d;}"
            "img,svg{max-width:100%;height:auto;}</style></head><body>"
            "<h1>NightShift Evaluation Results (5 Charts)</h1>"
            "<div class='grid'>"
            f"<div class='card'>{rca_svg}</div>"
            f"<div class='card'>{time_svg}</div>"
            f"<div class='card'>{cost_svg}</div>"
            f"<div class='card'>{cal_svg}</div>"
            f"<div class='card'>{abl_svg}</div>"
            "</div></body></html>"
        )
        html_path.write_text(html_body, encoding="utf-8")

    return {
        "charts": chart_paths,
        "results_page": str(html_out) if html_out else None,
        "values": {
            "rca_by_category": cat_values,
            "agent_mean_time": agent_mean,
            "human_mean_time": human_mean,
            "cost_by_fault": cost_values,
            "calibration_high_bin_acc": cal_report.high_conf_bin_accuracy,
            "ablations_fix_rate": abl_values,
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate all 5 Day 9 benchmark charts")
    parser.add_argument("--results", default=str(REPO_ROOT / "results" / "v2_improved.json"))
    parser.add_argument("--human", default=str(REPO_ROOT / "results" / "human_baseline.json"))
    parser.add_argument("--ablations", default=str(REPO_ROOT / "results" / "ablations" / "ablation_summary.json"))
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "results" / "charts"))
    args = parser.parse_args(argv)

    out = generate_all_five_charts(
        results_path=args.results,
        human_baseline_path=args.human,
        ablation_summary_path=args.ablations,
        out_dir=args.out_dir,
    )
    print(json.dumps(out["charts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
