"""Benchmark Results Aggregator & Chart Generator (Day 7 Task A3).

Computes exact evaluation metrics (RCA Top-1/Top-3 accuracy, Fix Success Rate,
Unsafe Rate, Infra Error Rate, Stage Latency means/median/p95, Token & Cost totals)
on `RunRecord` collections, and generates self-contained SVG visualization charts.

Owner: Person A (Systems & Proof)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from contracts.models import RunRecord


def _percentile(sorted_vals: Sequence[float], pct: float) -> float:
    """Compute linear-interpolated percentile (0..100) on a non-empty sorted sequence."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    return float(sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f]))


def _to_record(item: Union[RunRecord, Dict[str, Any]]) -> RunRecord:
    if isinstance(item, RunRecord):
        return item
    if isinstance(item, dict) and "run_record" in item and isinstance(item["run_record"], dict):
        return RunRecord(**item["run_record"])
    return RunRecord(**item)


def aggregate_results(
    records: Iterable[Union[RunRecord, Dict[str, Any]]],
    *,
    run_entries: Optional[Sequence[Dict[str, Any]]] = None,
    category_by_fault: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Aggregate exact accuracy, timing, cost, and flake metrics across RunRecords."""
    parsed: List[RunRecord] = [_to_record(r) for r in records]
    n = len(parsed)

    infra_error_count = 0
    if run_entries is not None:
        infra_error_count = sum(1 for e in run_entries if e.get("status") == "infra_error")

    if n == 0:
        return {
            "total_runs": 0,
            "rca_top1_count": 0,
            "rca_top3_count": 0,
            "fix_ok_count": 0,
            "unsafe_count": 0,
            "infra_error_count": infra_error_count,
            "rca_top1_accuracy": 0.0,
            "rca_top3_accuracy": 0.0,
            "fix_success_rate": 0.0,
            "unsafe_rate": 0.0,
            "infra_error_rate": 0.0,
            "mean_t_detect": 0.0,
            "mean_t_rca": 0.0,
            "mean_t_fix": 0.0,
            "mean_t_verified": 0.0,
            "mean_total_time": 0.0,
            "median_total_time": 0.0,
            "p95_total_time": 0.0,
            "total_tokens": 0,
            "mean_tokens": 0.0,
            "total_cost_usd": 0.0,
            "mean_cost_usd": 0.0,
            "by_category": {},
        }

    top1_count = sum(1 for r in parsed if r.rca_correct_top1)
    top3_count = sum(1 for r in parsed if r.rca_correct_top3)
    fix_count = sum(1 for r in parsed if r.fix_ok)
    unsafe_count = sum(1 for r in parsed if r.unsafe)

    t_detect_list = [float(r.t_detect) for r in parsed]
    t_rca_list = [float(r.t_rca) for r in parsed]
    t_fix_list = [float(r.t_fix) for r in parsed]
    t_verified_list = [float(r.t_verified) for r in parsed]
    total_times = sorted(
        float(r.t_detect + r.t_rca + r.t_fix + r.t_verified) for r in parsed
    )

    total_tokens = sum(int(r.tokens) for r in parsed)
    total_cost = sum(float(r.cost_usd) for r in parsed)

    by_category: Dict[str, Dict[str, Any]] = {}
    if category_by_fault:
        grouped: Dict[str, List[RunRecord]] = {}
        for rec in parsed:
            cat = category_by_fault.get(rec.fault_id, "unknown")
            grouped.setdefault(cat, []).append(rec)
        for cat, cat_recs in sorted(grouped.items()):
            cn = len(cat_recs)
            c_top1 = sum(1 for r in cat_recs if r.rca_correct_top1)
            c_top3 = sum(1 for r in cat_recs if r.rca_correct_top3)
            c_fix = sum(1 for r in cat_recs if r.fix_ok)
            c_time = sum(r.t_detect + r.t_rca + r.t_fix + r.t_verified for r in cat_recs)
            c_cost = sum(r.cost_usd for r in cat_recs)
            by_category[cat] = {
                "count": cn,
                "rca_top1_accuracy": round(c_top1 / cn, 6),
                "rca_top3_accuracy": round(c_top3 / cn, 6),
                "fix_success_rate": round(c_fix / cn, 6),
                "mean_total_time": round(c_time / cn, 6),
                "total_cost_usd": round(c_cost, 6),
            }

    return {
        "total_runs": n,
        "rca_top1_count": top1_count,
        "rca_top3_count": top3_count,
        "fix_ok_count": fix_count,
        "unsafe_count": unsafe_count,
        "infra_error_count": infra_error_count,
        "rca_top1_accuracy": round(top1_count / n, 6),
        "rca_top3_accuracy": round(top3_count / n, 6),
        "fix_success_rate": round(fix_count / n, 6),
        "unsafe_rate": round(unsafe_count / n, 6),
        "infra_error_rate": round(infra_error_count / n, 6),
        "mean_t_detect": round(sum(t_detect_list) / n, 6),
        "mean_t_rca": round(sum(t_rca_list) / n, 6),
        "mean_t_fix": round(sum(t_fix_list) / n, 6),
        "mean_t_verified": round(sum(t_verified_list) / n, 6),
        "mean_total_time": round(sum(total_times) / n, 6),
        "median_total_time": round(_percentile(total_times, 50.0), 6),
        "p95_total_time": round(_percentile(total_times, 95.0), 6),
        "total_tokens": total_tokens,
        "mean_tokens": round(total_tokens / n, 6),
        "total_cost_usd": round(total_cost, 6),
        "mean_cost_usd": round(total_cost / n, 6),
        "by_category": by_category,
    }


def _svg_bar_chart(
    title: str,
    bars: Sequence[tuple[str, float, str, str]],
    *,
    max_value: Optional[float] = None,
) -> str:
    """Render a clean dark-theme SVG horizontal bar chart."""
    width = 760
    bar_height = 30
    gap = 16
    top_pad = 64
    bottom_pad = 36
    left_pad = 210
    right_pad = 110
    chart_w = width - left_pad - right_pad
    height = top_pad + len(bars) * (bar_height + gap) + bottom_pad

    peak = max_value if max_value is not None else max((v for _, v, _, _ in bars), default=1.0)
    if peak <= 0:
        peak = 1.0

    rows: List[str] = []
    for idx, (label, val, display_val, color) in enumerate(bars):
        y = top_pad + idx * (bar_height + gap)
        w = max(2.0, (val / peak) * chart_w) if val > 0 else 2.0
        rows.append(
            f'<text x="{left_pad - 12}" y="{y + 20}" fill="#e6edf3" '
            f'font-family="Segoe UI, Arial, sans-serif" font-size="13" text-anchor="end">{label}</text>'
            f'<rect x="{left_pad}" y="{y}" width="{chart_w}" height="{bar_height}" rx="4" fill="#1f242c"/>'
            f'<rect x="{left_pad}" y="{y}" width="{w:.1f}" height="{bar_height}" rx="4" fill="{color}"/>'
            f'<text x="{left_pad + chart_w + 10}" y="{y + 20}" fill="#e6edf3" '
            f'font-family="Consolas, monospace" font-size="13">{display_val}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" rx="8" fill="#0d1117"/>'
        f'<text x="24" y="36" fill="#58a6ff" font-family="Segoe UI, Arial, sans-serif" '
        f'font-size="18" font-weight="bold">{title}</text>'
        + "".join(rows)
        + "</svg>"
    )


def generate_charts(
    summary: Dict[str, Any],
    records: Iterable[Union[RunRecord, Dict[str, Any]]],
    out_dir: Union[str, Path],
) -> Dict[str, str]:
    """Generate SVG charts for accuracy, stage timing, and cost metrics."""
    parsed = [_to_record(r) for r in records]
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # 1. Accuracy Chart
    acc_svg = _svg_bar_chart(
        f"NightShift Benchmark Accuracy (N={summary.get('total_runs', 0)})",
        [
            ("RCA Top-1 Accuracy", summary.get("rca_top1_accuracy", 0.0) * 100.0, f"{summary.get('rca_top1_accuracy', 0.0):.1%}", "#58a6ff"),
            ("RCA Top-3 Accuracy", summary.get("rca_top3_accuracy", 0.0) * 100.0, f"{summary.get('rca_top3_accuracy', 0.0):.1%}", "#3fb950"),
            ("Fix Success Rate", summary.get("fix_success_rate", 0.0) * 100.0, f"{summary.get('fix_success_rate', 0.0):.1%}", "#a371f7"),
            ("Unsafe Action Rate", summary.get("unsafe_rate", 0.0) * 100.0, f"{summary.get('unsafe_rate', 0.0):.1%}", "#f85149"),
        ],
        max_value=100.0,
    )
    acc_file = out_path / "accuracy_chart.svg"
    acc_file.write_text(acc_svg, encoding="utf-8")

    # 2. Time Breakdown Chart
    time_svg = _svg_bar_chart(
        "Mean Stage Latency Breakdown (seconds)",
        [
            ("Detection (t_detect)", summary.get("mean_t_detect", 0.0), f"{summary.get('mean_t_detect', 0.0):.2f}s", "#58a6ff"),
            ("RCA (t_rca)", summary.get("mean_t_rca", 0.0), f"{summary.get('mean_t_rca', 0.0):.2f}s", "#d29922"),
            ("Fix Proposal (t_fix)", summary.get("mean_t_fix", 0.0), f"{summary.get('mean_t_fix', 0.0):.2f}s", "#a371f7"),
            ("Verification (t_verified)", summary.get("mean_t_verified", 0.0), f"{summary.get('mean_t_verified', 0.0):.2f}s", "#3fb950"),
            ("Mean Total MTTR", summary.get("mean_total_time", 0.0), f"{summary.get('mean_total_time', 0.0):.2f}s", "#79c0ff"),
        ],
    )
    time_file = out_path / "time_chart.svg"
    time_file.write_text(time_svg, encoding="utf-8")

    # 3. Cost Chart (top runs or summary)
    cost_bars = [
        (r.fault_id[:24], float(r.cost_usd), f"${r.cost_usd:.4f} ({r.tokens} tok)", "#d29922")
        for r in parsed[:12]
    ]
    if not cost_bars:
        cost_bars = [("No runs", 0.0, "$0.0000", "#d29922")]
    cost_svg = _svg_bar_chart(
        f"Cost & Token Usage (Total: ${summary.get('total_cost_usd', 0.0):.4f})",
        cost_bars,
    )
    cost_file = out_path / "cost_chart.svg"
    cost_file.write_text(cost_svg, encoding="utf-8")

    return {
        "accuracy_chart": str(acc_file),
        "time_chart": str(time_file),
        "cost_chart": str(cost_file),
    }


def load_results_and_aggregate(results_json: Union[str, Path]) -> Dict[str, Any]:
    """Load results.json and compute fresh aggregate metrics."""
    data = json.loads(Path(results_json).read_text(encoding="utf-8"))
    records = data.get("records", [])
    run_entries = data.get("runs", [])
    return aggregate_results(records, run_entries=run_entries)
