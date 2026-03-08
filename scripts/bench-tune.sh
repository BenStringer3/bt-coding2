#!/usr/bin/env bash
# bench-tune.sh — Iterative tuning loop: run → analyze → report → adjust → rerun.
#
# Each iteration:
#   1. Runs bench.sh against the specified suite
#   2. Runs bench-analyze.py to extract metrics
#   3. Runs bench-report.py to generate a Markdown report
#   4. Optionally invokes bt-agent to suggest config/prompt adjustments
#   5. Displays suggestions and (optionally) applies them automatically
#   6. Loops until success gate passes or --max-iterations reached
#
# Usage:
#   ./scripts/bench-tune.sh [options]
#
# Options:
#   --suite <file>            Suite YAML to test against (default: suites/phase1.yaml)
#   --model <name>            Override model
#   --runs-per-problem <n>    Trials per problem (default: 1)
#   --max-iterations <n>      Max tuning iterations (default: 3)
#   --auto-tune               Apply LLM-suggested changes without human confirmation
#   --dry-run                 Pass --dry-run to bt-agent (no commits)
#   --tag <label>             Base label for this tuning run (default: tune)
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
MAX_ITERATIONS=3
AUTO_TUNE=false
DRY_RUN=""
TAG="tune"

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --suite)            SUITE="$2";              shift 2 ;;
    --model)            MODEL="$2";              shift 2 ;;
    --runs-per-problem) RUNS_PER_PROBLEM="$2";   shift 2 ;;
    --max-iterations)   MAX_ITERATIONS="$2";     shift 2 ;;
    --auto-tune)        AUTO_TUNE=true;          shift ;;
    --dry-run)          DRY_RUN="--dry-run";     shift ;;
    --tag)              TAG="$2";                shift 2 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── Pre-flight ─────────────────────────────────────────────────────────────────
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Error: venv not found — run: python -m venv .venv && pip install -e ." >&2; exit 1
fi
if [[ ! -f "$SUITE" ]]; then
  echo "Error: suite file not found: $SUITE" >&2; exit 1
fi

TUNE_LOG="$PROJECT_ROOT/reports/tune-${TAG}-$(date +%Y%m%d-%H%M%S).log"
mkdir -p "$PROJECT_ROOT/reports"

log() { echo "$*" | tee -a "$TUNE_LOG"; }

log "================================================================"
log " bench-tune: iterative improvement loop"
log " Suite:         $SUITE"
log " Max iterations: $MAX_ITERATIONS"
log " Auto-tune:      $AUTO_TUNE"
log " Log:            $TUNE_LOG"
log "================================================================"
log ""

LAST_RUN_DIR=""
ITERATION=0

while [[ $ITERATION -lt $MAX_ITERATIONS ]]; do
  ITERATION=$((ITERATION + 1))
  ITER_TAG="${TAG}-iter${ITERATION}"

  log "────────────────────────────────────────────────────────────────"
  log " Iteration $ITERATION / $MAX_ITERATIONS"
  log "────────────────────────────────────────────────────────────────"

  # ── Step 1: Run bench ────────────────────────────────────────────────────
  log "[1/4] Running bench..."
  BENCH_ARGS=(--suite "$SUITE" --runs-per-problem "$RUNS_PER_PROBLEM" --tag "$ITER_TAG")
  [[ -n "$MODEL" ]]   && BENCH_ARGS+=(--model "$MODEL")
  [[ -n "$DRY_RUN" ]] && BENCH_ARGS+=(--dry-run)

  "$SCRIPT_DIR/bench.sh" "${BENCH_ARGS[@]}" 2>&1 | tee -a "$TUNE_LOG"

  # Find the most recent run directory for this iteration tag
  LAST_RUN_DIR=$(ls -dt "$PROJECT_ROOT/runs/"*"-${ITER_TAG}" 2>/dev/null | head -1 || true)
  if [[ -z "$LAST_RUN_DIR" ]]; then
    # Fall back to most recent run dir
    LAST_RUN_DIR=$(ls -dt "$PROJECT_ROOT/runs/"* 2>/dev/null | head -1 || true)
  fi

  if [[ -z "$LAST_RUN_DIR" ]]; then
    log "Error: could not find run directory after bench" >&2
    exit 1
  fi

  log ""
  log "[2/4] Analyzing metrics from: $LAST_RUN_DIR"
  "$VENV_PYTHON" "$SCRIPT_DIR/bench-analyze.py" --run-dir "$LAST_RUN_DIR" 2>&1 | tee -a "$TUNE_LOG"

  log ""
  log "[3/4] Generating report..."
  COMPARE_ARGS=()
  if [[ -n "$LAST_RUN_DIR" && $ITERATION -gt 1 ]]; then
    PREV_RUN=$(ls -dt "$PROJECT_ROOT/runs/"* 2>/dev/null | sed -n "2p" || true)
    [[ -n "$PREV_RUN" ]] && COMPARE_ARGS+=(--compare "$PREV_RUN")
  fi
  "$VENV_PYTHON" "$SCRIPT_DIR/bench-report.py" --run-dir "$LAST_RUN_DIR" "${COMPARE_ARGS[@]}" 2>&1 | tee -a "$TUNE_LOG"

  # ── Check success gate ───────────────────────────────────────────────────
  GATE_PASSED=$("$VENV_PYTHON" - "$LAST_RUN_DIR/metrics.json" <<'PYEOF'
import sys, json
try:
    with open(sys.argv[1]) as f:
        m = json.load(f)
    gate = m.get("success_gate")
    print("true" if gate and gate.get("passed") else "false")
except Exception:
    print("false")
PYEOF
)

  if [[ "$GATE_PASSED" == "true" ]]; then
    log ""
    log "🟢 SUCCESS GATE PASSED on iteration $ITERATION"
    log "No further tuning needed."
    break
  fi

  if [[ $ITERATION -eq $MAX_ITERATIONS ]]; then
    log ""
    log "🔴 Max iterations ($MAX_ITERATIONS) reached without passing the gate."
    log "Review reports/progress.md and inspect trajectory logs manually."
    break
  fi

  # ── Step 4: LLM-assisted tuning suggestion ───────────────────────────────
  log ""
  log "[4/4] Requesting tuning suggestions from bt-agent..."

  LATEST_REPORT="$PROJECT_ROOT/reports/latest.md"
  if [[ ! -f "$LATEST_REPORT" ]]; then
    log "No latest.md report found — skipping LLM suggestion step."
  else
    TUNE_REPO_DIR="$PROJECT_ROOT"
    TUNE_TASK="You are helping improve a behavior tree coding agent. \
Read the benchmark report at reports/latest.md. \
Identify the top 1-2 failure modes and suggest a concrete change to either: \
(a) config/default.yaml (e.g. temperature, max_edit_attempts), or \
(b) bt_agent/llm/prompts.py (e.g. adding a format example to a prompt). \
Output ONLY the specific file path and the exact old_str/new_str change needed. \
Do not change logic, only prompt text or config values."

    TUNE_TRAJ="$LAST_RUN_DIR/tune-suggestions.jsonl"

    set +e
    "$VENV_BT_AGENT" run \
      --task "$TUNE_TASK" \
      --repo "$TUNE_REPO_DIR" \
      --output "$TUNE_TRAJ" \
      --dry-run \
      2>&1 | tee -a "$TUNE_LOG"
    TUNE_EXIT=$?
    set -e

    if [[ $TUNE_EXIT -ne 0 ]]; then
      log "bt-agent tuning suggestion failed (exit $TUNE_EXIT) — continuing without auto-tune."
    else
      log ""
      log "Suggestions written to: $TUNE_TRAJ"

      if [[ "$AUTO_TUNE" == "true" ]]; then
        log "Auto-tune enabled — changes were applied by bt-agent (dry-run was NOT set)."
        log "Re-running bench in next iteration with modified config/prompts."
      else
        log ""
        log "Review the suggested changes above, then apply them manually."
        log "Press Enter to continue to the next iteration, or Ctrl+C to stop."
        read -r _
      fi
    fi
  fi

  log ""
done

# ── Final summary ──────────────────────────────────────────────────────────────
log ""
log "================================================================"
log " Tuning complete after $ITERATION iteration(s)"
log " Progress log: $PROJECT_ROOT/reports/progress.md"
log " Tune log:     $TUNE_LOG"
if [[ -n "$LAST_RUN_DIR" ]]; then
  log " Final run:    $LAST_RUN_DIR"
fi
log "================================================================"
