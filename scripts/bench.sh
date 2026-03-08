#!/usr/bin/env bash
# bench.sh — Run a suite of problems against one or more trees and collect results.
#
# Usage:
#   ./scripts/bench.sh [options]
#
# Options:
#   --suite <file>            Suite YAML (default: suites/phase1.yaml)
#   --model <name>            Override model from config/default.yaml
#   --runs-per-problem <n>    Trials per problem/tree combo (default: 1)
#   --dry-run                 Pass --dry-run to bt-agent (no commits)
#   --tag <label>             Human label for this bench run
#   --max-attempts <n>        Override max_edit_attempts for all runs
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
VENV_BT_AGENT="$PROJECT_ROOT/.venv/bin/bt-agent"

# ── Defaults ──────────────────────────────────────────────────────────────────
SUITE="$PROJECT_ROOT/suites/phase1.yaml"
MODEL=""
RUNS_PER_PROBLEM=1
DRY_RUN=""
TAG="bench"
MAX_ATTEMPTS=""

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --suite)         SUITE="$2";              shift 2 ;;
    --model)         MODEL="$2";              shift 2 ;;
    --runs-per-problem) RUNS_PER_PROBLEM="$2"; shift 2 ;;
    --dry-run)       DRY_RUN="--dry-run";     shift ;;
    --tag)           TAG="$2";                shift 2 ;;
    --max-attempts)  MAX_ATTEMPTS="$2";       shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── Pre-flight ─────────────────────────────────────────────────────────────────
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Error: venv not found — run: python -m venv .venv && pip install -e ." >&2; exit 1
fi
if [[ ! -x "$VENV_BT_AGENT" ]]; then
  echo "Error: bt-agent not found — run: pip install -e ." >&2; exit 1
fi
if [[ ! -f "$SUITE" ]]; then
  echo "Error: suite file not found: $SUITE" >&2; exit 1
fi

# ── Read suite YAML via Python ────────────────────────────────────────────────
SUITE_JSON=$("$VENV_PYTHON" - "$SUITE" <<'PYEOF'
import sys, yaml, json
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
print(json.dumps(data))
PYEOF
)

SUITE_NAME=$(echo "$SUITE_JSON" | "$VENV_PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d.get('name','suite'))")
PROBLEM_COUNT=$(echo "$SUITE_JSON" | "$VENV_PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('problems',[])))")

# ── Create run directory ───────────────────────────────────────────────────────
TS=$(date +"%Y%m%d-%H%M%S")
RUN_ID="${TS}-${TAG}"
RUN_DIR="$PROJECT_ROOT/runs/$RUN_ID"
mkdir -p "$RUN_DIR"

echo "================================================================"
echo " bt-agent benchmark"
echo " Suite:    $SUITE_NAME"
echo " Problems: $PROBLEM_COUNT"
echo " Trials:   $RUNS_PER_PROBLEM per problem"
echo " Run dir:  $RUN_DIR"
echo "================================================================"
echo ""

# ── Write manifest ─────────────────────────────────────────────────────────────
"$VENV_PYTHON" - "$SUITE" "$RUN_DIR/manifest.json" "$MODEL" "$RUNS_PER_PROBLEM" "$TS" "$TAG" <<'PYEOF'
import sys, yaml, json
from datetime import datetime

suite_path, out_path, model_override, runs_per, ts, tag = sys.argv[1:]
with open(suite_path) as f:
    suite = yaml.safe_load(f)

manifest = {
    "run_id": f"{ts}-{tag}",
    "timestamp": ts,
    "tag": tag,
    "suite_file": suite_path,
    "suite_name": suite.get("name", ""),
    "model_override": model_override or None,
    "runs_per_problem": int(runs_per),
    "problems": suite.get("problems", []),
    "success_gate": suite.get("success_gate", {}),
}
with open(out_path, "w") as f:
    json.dump(manifest, f, indent=2)
print(f"Manifest: {out_path}")
PYEOF

# ── Iterate over problems ──────────────────────────────────────────────────────
TOTAL=0
PASSED=0
FAILED=0

"$VENV_PYTHON" - "$SUITE" <<'PYEOF' > "$RUN_DIR/_problems.tsv"
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
for p in data.get("problems", []):
    fixture = p["fixture"]
    for tree in p.get("trees", ["run"]):
        print(f"{p['id']}\t{fixture}\t{tree}")
PYEOF

while IFS=$'\t' read -r PROB_ID FIXTURE_REL TREE; do
  FIXTURE_DIR="$PROJECT_ROOT/$FIXTURE_REL"
  PROBLEM_YAML="$FIXTURE_DIR/problem.yaml"

  if [[ ! -f "$PROBLEM_YAML" ]]; then
    echo "SKIP $PROB_ID — problem.yaml not found at $FIXTURE_DIR" >&2
    continue
  fi

  TASK=$("$VENV_PYTHON" -c "
import sys, yaml
with open('$PROBLEM_YAML') as f:
    d = yaml.safe_load(f)
print(d['task'].strip())
")

  for TRIAL in $(seq 1 "$RUNS_PER_PROBLEM"); do
    TRIAL_DIR="$RUN_DIR/$PROB_ID/trial-$TRIAL"
    mkdir -p "$TRIAL_DIR"

    # Copy fixture source files (skip problem.yaml and test_solution.py)
    find "$FIXTURE_DIR" -maxdepth 1 -type f \
      ! -name "problem.yaml" ! -name "test_solution.py" \
      -exec cp {} "$TRIAL_DIR/" \;

    # Fresh git repo
    (cd "$TRIAL_DIR" && git init -q && git add . && git commit -q -m "Initial: $PROB_ID")

    echo "── $PROB_ID / $TREE / trial $TRIAL ──"

    TRAJECTORY="$TRIAL_DIR/trajectory.jsonl"
    START_S=$(date +%s)

    # Build bt-agent args
    BT_ARGS=("$TREE" --task "$TASK" --repo "$TRIAL_DIR" --output "$TRAJECTORY")
    [[ -n "$DRY_RUN" ]]     && BT_ARGS+=("--dry-run")
    [[ -n "$MODEL" ]]        && BT_ARGS+=(--model "$MODEL")
    [[ -n "$MAX_ATTEMPTS" ]] && BT_ARGS+=(--max-attempts "$MAX_ATTEMPTS")

    set +e
    "$VENV_BT_AGENT" "${BT_ARGS[@]}" 2>&1 | tee "$TRIAL_DIR/agent.log"
    EXIT_CODE=$?
    set -e
    END_S=$(date +%s)
    WALL_S=$((END_S - START_S))

    # Capture diff
    (cd "$TRIAL_DIR" && git diff HEAD~1..HEAD 2>/dev/null || true) > "$TRIAL_DIR/diff.patch"
    DIFF_LINES=$(wc -l < "$TRIAL_DIR/diff.patch" || echo 0)

    # Determine committed status from trajectory
    COMMITTED=$("$VENV_PYTHON" - "$TRAJECTORY" <<'PYEOF' 2>/dev/null || echo "false"
import sys, json
committed = False
if len(sys.argv) > 1:
    try:
        with open(sys.argv[1]) as f:
            for line in f:
                entry = json.loads(line.strip())
                if entry.get("blackboard_snapshot", {}).get("committed"):
                    committed = True
    except Exception:
        pass
print("true" if committed else "false")
PYEOF
)

    # Write per-trial result.json
    "$VENV_PYTHON" - "$TRIAL_DIR/result.json" <<PYEOF
import json
result = {
    "problem_id": "$PROB_ID",
    "tree": "$TREE",
    "trial": $TRIAL,
    "exit_code": $EXIT_CODE,
    "wall_time_s": $WALL_S,
    "committed": $( [[ "$COMMITTED" == "true" ]] && echo "true" || echo "false" ),
    "diff_lines": $DIFF_LINES,
    "success": $( [[ $EXIT_CODE -eq 0 ]] && echo "true" || echo "false" ),
}
with open("$TRIAL_DIR/result.json", "w") as f:
    json.dump(result, f, indent=2)
PYEOF

    TOTAL=$((TOTAL + 1))
    if [[ $EXIT_CODE -eq 0 ]]; then
      PASSED=$((PASSED + 1))
      echo "  PASS (${WALL_S}s)"
    else
      FAILED=$((FAILED + 1))
      echo "  FAIL (exit=$EXIT_CODE, ${WALL_S}s)"
    fi
    echo ""

  done
done < "$RUN_DIR/_problems.tsv"

rm -f "$RUN_DIR/_problems.tsv"

# ── Aggregate results.json ────────────────────────────────────────────────────
"$VENV_PYTHON" - "$RUN_DIR" "$TOTAL" "$PASSED" "$FAILED" <<'PYEOF'
import sys, json, pathlib

run_dir = pathlib.Path(sys.argv[1])
total, passed, failed = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])

all_results = []
for result_file in sorted(run_dir.rglob("result.json")):
    with open(result_file) as f:
        all_results.append(json.load(f))

aggregate = {
    "total_trials": total,
    "passed": passed,
    "failed": failed,
    "success_rate": round(passed / total, 3) if total > 0 else 0,
    "trials": all_results,
}
out = run_dir / "results.json"
with open(out, "w") as f:
    json.dump(aggregate, f, indent=2)
print(f"Results: {out}")
PYEOF

# ── Summary ────────────────────────────────────────────────────────────────────
echo "================================================================"
echo " Results: $PASSED/$TOTAL passed  ($(( PASSED * 100 / (TOTAL > 0 ? TOTAL : 1) ))%)"
echo " Run dir: $RUN_DIR"
echo "================================================================"
echo ""

# ── Auto-analyze ───────────────────────────────────────────────────────────────
if [[ -f "$SCRIPT_DIR/bench-analyze.py" ]]; then
  echo "Running analysis..."
  "$VENV_PYTHON" "$SCRIPT_DIR/bench-analyze.py" --run-dir "$RUN_DIR"
fi

# ── Auto-report ────────────────────────────────────────────────────────────────
if [[ -f "$SCRIPT_DIR/bench-report.py" ]]; then
  echo "Generating report..."
  "$VENV_PYTHON" "$SCRIPT_DIR/bench-report.py" --run-dir "$RUN_DIR"
fi
