#!/usr/bin/env python3
"""bench-analyze.py — Parse trajectory logs from a bench run and produce metrics.json.

Usage:
    python scripts/bench-analyze.py --run-dir runs/<id>
"""
import argparse
import json
import pathlib
import re
from collections import defaultdict


def parse_trajectory(trajectory_path: pathlib.Path) -> dict:
    """Parse a single trajectory.jsonl and return structured metrics."""
    entries = []
    try:
        with open(trajectory_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"parse_error": True, "entries": 0}

    if not entries:
        return {"parse_error": False, "entries": 0, "success": False}

    # Final root status: look for the last entry at a Sequence root node
    # Root node is typically the last entry or has the most complete snapshot
    final_committed = False
    last_error = None
    node_statuses = defaultdict(list)
    llm_calls = []
    failure_nodes = []
    retry_count = 0
    edit_attempts_max = 0

    for entry in entries:
        node = entry.get("node", "")
        status = entry.get("status", "")
        bb = entry.get("blackboard_snapshot") or {}
        llm = entry.get("llm_call") or {}
        error = entry.get("error")

        node_statuses[node].append(status)

        if bb.get("committed"):
            final_committed = True
        if bb.get("last_error"):
            last_error = bb["last_error"]
        if bb.get("edit_attempts", 0) > edit_attempts_max:
            edit_attempts_max = bb["edit_attempts"]

        if status == "FAILURE":
            failure_nodes.append(node)
            if error:
                last_error = error

        if llm:
            llm_calls.append({
                "node": node,
                "prompt_tokens": llm.get("prompt_tokens", 0),
                "completion_tokens": llm.get("completion_tokens", 0),
            })

    # Count retries as the number of times GenerateEdit or GenerateFileEdit ran
    edit_node_names = {"GenerateEdit", "GenerateFileEdit", "GenerateEdit[*]"}
    for node_name, statuses in node_statuses.items():
        if node_name in edit_node_names or "GenerateEdit" in node_name:
            retry_count = max(0, len(statuses) - 1)

    # Success = committed or final root was SUCCESS
    success = final_committed
    if not success:
        # Check if root sequence returned SUCCESS
        for entry in reversed(entries):
            node = entry.get("node", "")
            if "Root" in node or "Sequence" in node:
                if entry.get("status") == "SUCCESS":
                    success = True
                break

    # Token totals
    total_prompt = sum(c["prompt_tokens"] for c in llm_calls)
    total_completion = sum(c["completion_tokens"] for c in llm_calls)

    # Failure mode classification
    failure_modes = []
    for node in failure_nodes:
        if last_error:
            if "not found" in last_error.lower() or "old_str" in last_error.lower():
                failure_modes.append(f"{node}.old_str_not_found")
            elif "syntax" in last_error.lower() or "parse" in last_error.lower():
                failure_modes.append(f"{node}.syntax_error")
            elif "import" in last_error.lower():
                failure_modes.append(f"{node}.import_error")
            elif "json" in last_error.lower():
                failure_modes.append(f"{node}.json_parse_error")
            else:
                failure_modes.append(f"{node}.other")
        else:
            failure_modes.append(f"{node}.unknown")

    # Phase breakdown: group nodes into logical phases
    phase_tokens = {"gather": 0, "plan": 0, "edit": 0, "validate": 0, "commit": 0}
    phase_map = {
        "gather": {"BuildRepoMap", "LocateRelevantFiles", "ExtractFilesAndIntent",
                   "BuildDependencyGraph", "PrioritizeEditOrder"},
        "plan":   {"PlanEdits", "PlanFileChanges", "UnderstandTask"},
        "edit":   {"GenerateEdit", "ApplyEdit", "ReadTargetFile", "GenerateFileEdit"},
        "validate": {"ValidateEdit", "CheckImportConsistency", "CheckCircularDependencies"},
        "commit": {"GenerateCommitMsg", "GitCommit", "CommitAllChanges"},
    }
    for call in llm_calls:
        node_name = call["node"]
        tokens = call["prompt_tokens"] + call["completion_tokens"]
        matched = False
        for phase, nodes in phase_map.items():
            if node_name in nodes or any(n in node_name for n in nodes):
                phase_tokens[phase] += tokens
                matched = True
                break
        if not matched:
            phase_tokens["edit"] += tokens  # default bucket

    return {
        "parse_error": False,
        "entries": len(entries),
        "success": success,
        "committed": final_committed,
        "retry_count": retry_count,
        "edit_attempts": edit_attempts_max,
        "llm_call_count": len(llm_calls),
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_tokens": total_prompt + total_completion,
        "failure_nodes": failure_nodes,
        "failure_modes": failure_modes,
        "last_error": last_error,
        "phase_tokens": phase_tokens,
    }


def analyze_run(run_dir: pathlib.Path) -> dict:
    """Walk a run directory, parse all trajectories, produce aggregated metrics."""
    manifest_path = run_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)

    results_path = run_dir / "results.json"
    results = {}
    if results_path.exists():
        with open(results_path) as f:
            results = json.load(f)

    per_problem: dict[str, list[dict]] = defaultdict(list)
    failure_mode_counts: dict[str, int] = defaultdict(int)

    # Find all trial directories
    for result_file in sorted(run_dir.rglob("result.json")):
        trial_dir = result_file.parent
        prob_id = trial_dir.parent.name
        trajectory = trial_dir / "trajectory.jsonl"

        trial_result = {}
        if result_file.exists():
            with open(result_file) as f:
                trial_result = json.load(f)

        traj_metrics = parse_trajectory(trajectory)

        combined = {**trial_result, **traj_metrics}
        combined["trial_dir"] = str(trial_dir.relative_to(run_dir))
        per_problem[prob_id].append(combined)

        for mode in traj_metrics.get("failure_modes", []):
            failure_mode_counts[mode] += 1

    # Compute per-problem aggregates
    per_problem_summary = {}
    all_successes = []
    all_retries = []
    all_tokens = []
    all_wall_times = []
    all_llm_calls = []

    for prob_id, trials in per_problem.items():
        successes = [t.get("success", False) for t in trials]
        retries = [t.get("retry_count", 0) for t in trials]
        tokens = [t.get("total_tokens", 0) for t in trials]
        wall_times = [t.get("wall_time_s", 0) for t in trials]
        llm_calls = [t.get("llm_call_count", 0) for t in trials]

        per_problem_summary[prob_id] = {
            "trials": len(trials),
            "pass_count": sum(successes),
            "success_rate": round(sum(successes) / len(successes), 3) if successes else 0,
            "avg_retries": round(sum(retries) / len(retries), 2) if retries else 0,
            "avg_tokens": round(sum(tokens) / len(tokens)) if tokens else 0,
            "avg_wall_time_s": round(sum(wall_times) / len(wall_times), 1) if wall_times else 0,
            "avg_llm_calls": round(sum(llm_calls) / len(llm_calls), 1) if llm_calls else 0,
            "failure_modes": [m for t in trials for m in t.get("failure_modes", [])],
        }

        all_successes.extend(successes)
        all_retries.extend(retries)
        all_tokens.extend(tokens)
        all_wall_times.extend(wall_times)
        all_llm_calls.extend(llm_calls)

    total = len(all_successes)
    passed = sum(all_successes)

    summary = {
        "total_trials": total,
        "passed": passed,
        "failed": total - passed,
        "success_rate": round(passed / total, 3) if total > 0 else 0,
        "avg_retries": round(sum(all_retries) / len(all_retries), 2) if all_retries else 0,
        "avg_tokens": round(sum(all_tokens) / len(all_tokens)) if all_tokens else 0,
        "avg_prompt_tokens": 0,
        "avg_completion_tokens": 0,
        "avg_wall_time_s": round(sum(all_wall_times) / len(all_wall_times), 1) if all_wall_times else 0,
        "avg_llm_calls": round(sum(all_llm_calls) / len(all_llm_calls), 1) if all_llm_calls else 0,
    }

    # Check against success gate if defined
    gate = manifest.get("success_gate", {})
    gate_result = None
    if gate:
        min_sr = gate.get("min_success_rate", 0)
        max_retries = gate.get("max_avg_retries", float("inf"))
        max_llm = gate.get("max_avg_llm_calls", float("inf"))
        gate_result = {
            "passed": (
                summary["success_rate"] >= min_sr
                and summary["avg_retries"] <= max_retries
                and summary["avg_llm_calls"] <= max_llm
            ),
            "min_success_rate": min_sr,
            "actual_success_rate": summary["success_rate"],
            "max_avg_retries": max_retries,
            "actual_avg_retries": summary["avg_retries"],
        }

    # Build recommendations from failure patterns
    recommendations = _generate_recommendations(failure_mode_counts, summary)

    metrics = {
        "run_id": manifest.get("run_id", run_dir.name),
        "suite_name": manifest.get("suite_name", ""),
        "model": manifest.get("model_override") or "(default from config)",
        "summary": summary,
        "per_problem": per_problem_summary,
        "failure_modes": dict(sorted(failure_mode_counts.items(), key=lambda x: -x[1])),
        "success_gate": gate_result,
        "recommendations": recommendations,
    }

    out_path = run_dir / "metrics.json"
    with open(out_path, "w") as f:
        json.dump(metrics, f, indent=2)

    return metrics


def _generate_recommendations(failure_modes: dict[str, int], summary: dict) -> list[str]:
    recs = []
    total_failures = sum(failure_modes.values())

    if total_failures == 0:
        return ["All trials passed — consider raising difficulty (next phase or more runs per problem)."]

    top_mode, top_count = max(failure_modes.items(), key=lambda x: x[1]) if failure_modes else ("", 0)

    if "old_str_not_found" in top_mode and top_count >= 2:
        recs.append(
            f"{top_count} failures in ApplyEdit.old_str_not_found — "
            "consider prompting the model to use shorter, more unique old_str excerpts, "
            "or increase the file window shown during GenerateEdit."
        )
    if any("syntax_error" in m for m in failure_modes):
        n = sum(v for k, v in failure_modes.items() if "syntax_error" in k)
        recs.append(
            f"{n} ValidateEdit syntax failures — confirm the model is not wrapping "
            "output in markdown fences, and check GenerateEdit prompt JSON schema clarity."
        )
    if any("json_parse_error" in m for m in failure_modes):
        n = sum(v for k, v in failure_modes.items() if "json_parse_error" in k)
        recs.append(
            f"{n} JSON parse errors — model is not producing valid JSON. "
            "Try temperature=0.0 or add a stricter output format example to the prompt."
        )
    if any("import_error" in m for m in failure_modes):
        recs.append(
            "Import errors detected — check that the LLM is not hallucinating library names."
        )

    if summary.get("avg_tokens", 0) > 1800:
        recs.append(
            f"High average token use ({summary['avg_tokens']:.0f}). "
            "Consider trimming PlanEdits or LocateRelevantFiles prompts."
        )
    if summary.get("avg_retries", 0) > 3:
        recs.append(
            f"High average retry count ({summary['avg_retries']:.1f}). "
            "The edit generation prompt may need clearer str_replace format examples."
        )

    if not recs:
        recs.append("No dominant failure pattern identified — inspect individual trajectory logs.")
    return recs


def main():
    parser = argparse.ArgumentParser(description="Analyze a bench run directory")
    parser.add_argument("--run-dir", required=True, type=pathlib.Path)
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.is_dir():
        print(f"Error: run-dir not found: {run_dir}")
        raise SystemExit(1)

    print(f"Analyzing: {run_dir}")
    metrics = analyze_run(run_dir)

    sr = metrics["summary"]["success_rate"]
    total = metrics["summary"]["total_trials"]
    passed = metrics["summary"]["passed"]
    print(f"Success rate: {passed}/{total} ({sr:.1%})")
    print(f"Avg retries:  {metrics['summary']['avg_retries']}")
    print(f"Avg tokens:   {metrics['summary']['avg_tokens']}")

    gate = metrics.get("success_gate")
    if gate:
        status = "PASS" if gate["passed"] else "FAIL"
        print(f"Phase gate:   {status} (threshold: {gate['min_success_rate']:.0%})")

    print(f"Metrics:      {run_dir / 'metrics.json'}")

    if metrics.get("recommendations"):
        print("\nRecommendations:")
        for rec in metrics["recommendations"]:
            print(f"  • {rec}")


if __name__ == "__main__":
    main()
