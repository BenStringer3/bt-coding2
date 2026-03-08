#!/usr/bin/env python3
"""bench-report.py — Generate a Markdown report from a bench run's metrics.

Usage:
    python scripts/bench-report.py --run-dir runs/<id>
    python scripts/bench-report.py --run-dir runs/<id> --compare runs/<previous-id>
"""
import argparse
import json
import pathlib
from datetime import datetime


REPORTS_DIR = pathlib.Path(__file__).parent.parent / "reports"
PROGRESS_FILE = REPORTS_DIR / "progress.md"


def load_json(path: pathlib.Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def _status_emoji(success: bool) -> str:
    return "✅" if success else "❌"


def _gate_badge(gate: dict | None) -> str:
    if gate is None:
        return ""
    return "🟢 GATE PASS" if gate.get("passed") else "🔴 GATE FAIL"


def generate_report(run_dir: pathlib.Path, compare_dir: pathlib.Path | None = None) -> str:
    manifest = load_json(run_dir / "manifest.json")
    metrics = load_json(run_dir / "metrics.json")
    results = load_json(run_dir / "results.json")

    if not metrics:
        return f"# Report Error\n\nNo metrics.json found in {run_dir}\nRun `bench-analyze.py` first.\n"

    compare_metrics = load_json(compare_dir / "metrics.json") if compare_dir else {}

    summary = metrics.get("summary", {})
    gate = metrics.get("success_gate")
    per_problem = metrics.get("per_problem", {})
    failure_modes = metrics.get("failure_modes", {})
    recommendations = metrics.get("recommendations", [])

    run_id = manifest.get("run_id", run_dir.name)
    suite_name = manifest.get("suite_name", metrics.get("suite_name", ""))
    model = manifest.get("model_override") or "(config default)"
    runs_per = manifest.get("runs_per_problem", 1)
    ts = manifest.get("timestamp", "")

    lines = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines += [
        f"# Benchmark Report: {suite_name}",
        f"",
        f"| Field | Value |",
        f"|-------|-------|",
        f"| Run ID | `{run_id}` |",
        f"| Date | {ts} |",
        f"| Model | `{model}` |",
        f"| Trials per problem | {runs_per} |",
        f"| Suite | `{manifest.get('suite_file', '')}` |",
        f"",
    ]

    # ── Overall summary ───────────────────────────────────────────────────────
    total = summary.get("total_trials", 0)
    passed = summary.get("passed", 0)
    sr = summary.get("success_rate", 0)
    avg_retries = summary.get("avg_retries", 0)
    avg_tokens = summary.get("avg_tokens", 0)
    avg_wall = summary.get("avg_wall_time_s", 0)
    avg_llm = summary.get("avg_llm_calls", 0)

    gate_str = _gate_badge(gate)
    lines += [
        f"## Overall Results  {gate_str}",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Success rate | **{passed}/{total}** ({sr:.1%}) |",
        f"| Avg retries | {avg_retries} |",
        f"| Avg tokens | {avg_tokens:,} |",
        f"| Avg wall time | {avg_wall}s |",
        f"| Avg LLM calls | {avg_llm} |",
        f"",
    ]

    if gate:
        lines += [
            f"### Phase Gate",
            f"",
            f"| Criterion | Threshold | Actual | Status |",
            f"|-----------|-----------|--------|--------|",
            f"| Success rate | ≥{gate['min_success_rate']:.0%} | {gate['actual_success_rate']:.1%} | "
            f"{'✅' if gate['actual_success_rate'] >= gate['min_success_rate'] else '❌'} |",
        ]
        if "max_avg_retries" in gate and gate["max_avg_retries"] != float("inf"):
            lines.append(
                f"| Avg retries | ≤{gate['max_avg_retries']} | {gate['actual_avg_retries']} | "
                f"{'✅' if gate['actual_avg_retries'] <= gate['max_avg_retries'] else '❌'} |"
            )
        lines.append("")

    # ── Comparison if provided ────────────────────────────────────────────────
    if compare_metrics:
        prev_sr = compare_metrics.get("summary", {}).get("success_rate", 0)
        prev_tokens = compare_metrics.get("summary", {}).get("avg_tokens", 0)
        prev_retries = compare_metrics.get("summary", {}).get("avg_retries", 0)
        delta_sr = sr - prev_sr
        delta_tokens = avg_tokens - prev_tokens
        delta_retries = avg_retries - prev_retries

        def _delta(val, invert=False):
            sign = "+" if val >= 0 else ""
            arrow = ("↑" if val > 0 else "↓") if val != 0 else "→"
            better = (val > 0) != invert
            mark = "✅" if better else "❌"
            return f"{sign}{val:.2g} {arrow} {mark}"

        lines += [
            f"## Comparison with Previous Run",
            f"",
            f"| Metric | Previous | Current | Delta |",
            f"|--------|----------|---------|-------|",
            f"| Success rate | {prev_sr:.1%} | {sr:.1%} | {_delta(delta_sr)} |",
            f"| Avg tokens | {prev_tokens:,} | {avg_tokens:,} | {_delta(delta_tokens, invert=True)} |",
            f"| Avg retries | {prev_retries} | {avg_retries} | {_delta(delta_retries, invert=True)} |",
            f"",
        ]

    # ── Per-problem table ─────────────────────────────────────────────────────
    lines += [
        f"## Per-Problem Results",
        f"",
        f"| Problem | Trials | Pass | Rate | Avg Retries | Avg Tokens | Avg Time |",
        f"|---------|--------|------|------|-------------|------------|----------|",
    ]
    for prob_id, pdata in sorted(per_problem.items()):
        n = pdata.get("trials", 0)
        p = pdata.get("pass_count", 0)
        psr = pdata.get("success_rate", 0)
        retries = pdata.get("avg_retries", 0)
        tokens = pdata.get("avg_tokens", 0)
        wall = pdata.get("avg_wall_time_s", 0)
        icon = "✅" if psr >= 0.9 else ("⚠️" if psr >= 0.5 else "❌")
        lines.append(
            f"| {icon} `{prob_id}` | {n} | {p} | {psr:.0%} | {retries} | {tokens:,} | {wall}s |"
        )
    lines.append("")

    # ── Failure mode analysis ─────────────────────────────────────────────────
    if failure_modes:
        lines += [
            f"## Failure Mode Analysis",
            f"",
            f"| Failure Mode | Count |",
            f"|--------------|-------|",
        ]
        for mode, count in sorted(failure_modes.items(), key=lambda x: -x[1]):
            lines.append(f"| `{mode}` | {count} |")
        lines.append("")

        # Breakdown by problem
        lines += ["### Failure Detail by Problem", ""]
        for prob_id, pdata in sorted(per_problem.items()):
            modes = pdata.get("failure_modes", [])
            if modes:
                mode_summary = ", ".join(f"`{m}`" for m in sorted(set(modes)))
                lines.append(f"- **{prob_id}**: {mode_summary}")
        lines.append("")

    # ── Recommendations ───────────────────────────────────────────────────────
    if recommendations:
        lines += [f"## Recommendations", f""]
        for rec in recommendations:
            lines.append(f"- {rec}")
        lines.append("")

    # ── Tree coverage ─────────────────────────────────────────────────────────
    trees_used = set()
    for prob_id, pdata in per_problem.items():
        for trial in results.get("trials", []):
            if trial.get("problem_id") == prob_id:
                trees_used.add(trial.get("tree", "run"))

    if trees_used:
        lines += [
            f"## Trees Tested",
            f"",
        ]
        for tree in sorted(trees_used):
            lines.append(f"- `{tree}`")
        lines.append("")

    lines += [f"---", f"*Generated by bench-report.py at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*", f""]
    return "\n".join(lines)


def append_progress_row(run_dir: pathlib.Path, metrics: dict, manifest: dict):
    """Append a one-line summary row to reports/progress.md."""
    REPORTS_DIR.mkdir(exist_ok=True)

    summary = metrics.get("summary", {})
    gate = metrics.get("success_gate")

    row = (
        f"| {manifest.get('timestamp', '')} "
        f"| {manifest.get('tag', run_dir.name)} "
        f"| {metrics.get('suite_name', '')} "
        f"| {manifest.get('model_override') or 'default'} "
        f"| {summary.get('success_rate', 0):.1%} "
        f"| {summary.get('avg_retries', 0)} "
        f"| {summary.get('avg_tokens', 0):,} "
        f"| {'PASS' if gate and gate.get('passed') else 'FAIL' if gate else 'N/A'} "
        f"| `{run_dir.name}` |"
    )

    header_needed = not PROGRESS_FILE.exists() or PROGRESS_FILE.stat().st_size == 0
    with open(PROGRESS_FILE, "a") as f:
        if header_needed:
            f.write("# Benchmark Progress\n\n")
            f.write(
                "| Timestamp | Tag | Suite | Model | Success Rate | Avg Retries | Avg Tokens | Gate | Run ID |\n"
                "|-----------|-----|-------|-------|-------------|-------------|------------|------|--------|\n"
            )
        f.write(row + "\n")


def main():
    parser = argparse.ArgumentParser(description="Generate a Markdown report from a bench run")
    parser.add_argument("--run-dir", required=True, type=pathlib.Path)
    parser.add_argument("--compare", type=pathlib.Path, default=None,
                        help="Previous run dir to compare against")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    compare_dir = args.compare.expanduser().resolve() if args.compare else None

    if not run_dir.is_dir():
        print(f"Error: run-dir not found: {run_dir}")
        raise SystemExit(1)

    # Auto-run analysis if metrics.json doesn't exist
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.exists():
        print("metrics.json not found — running bench-analyze.py first...")
        import subprocess, sys
        analyze_script = pathlib.Path(__file__).parent / "bench-analyze.py"
        subprocess.run([sys.executable, str(analyze_script), "--run-dir", str(run_dir)], check=True)

    manifest = load_json(run_dir / "manifest.json")
    metrics = load_json(metrics_path)

    report = generate_report(run_dir, compare_dir)

    # Write to reports/ directory
    REPORTS_DIR.mkdir(exist_ok=True)
    ts = manifest.get("timestamp", datetime.now().strftime("%Y%m%d-%H%M%S"))
    tag = manifest.get("tag", "bench")
    report_path = REPORTS_DIR / f"{ts}-{tag}-summary.md"
    report_path.write_text(report)

    # Also write a symlink/copy as latest.md
    latest = REPORTS_DIR / "latest.md"
    latest.write_text(report)

    print(f"Report: {report_path}")
    print(f"Latest: {latest}")

    append_progress_row(run_dir, metrics, manifest)
    print(f"Progress: {PROGRESS_FILE}")


if __name__ == "__main__":
    main()
