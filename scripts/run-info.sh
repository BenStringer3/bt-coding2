#!/usr/bin/env bash
# run-info.sh — helpers for the run-report skill
# Usage: run-info.sh [dir|problem|diff]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNS_DIR="$SCRIPT_DIR/../runs"
FIXTURES_DIR="$SCRIPT_DIR/../tests/fixtures"

RUNDIR=$(find "$RUNS_DIR" -name "trajectory.jsonl" | sort -r | head -1 | xargs -r dirname)

if [[ -z "$RUNDIR" ]]; then
  echo "(no run directory found)" >&2
  exit 1
fi

case "${1:-dir}" in
  dir)
    echo "$RUNDIR"
    ;;
  problem)
    SLUG=$(basename "$RUNDIR" | sed 's/-[0-9]\{8\}-[0-9]\{6\}$//')
    PROBLEM="$FIXTURES_DIR/$SLUG/problem.yaml"
    if [[ -f "$PROBLEM" ]]; then
      cat "$PROBLEM"
    else
      echo "(no problem.yaml found for slug: $SLUG)"
    fi
    ;;
  diff)
    cd "$RUNDIR"
    git log --oneline -3 && echo "---" && git diff HEAD~1 HEAD 2>/dev/null || echo "(no previous commit — initial state only)"
    ;;
  *)
    echo "Usage: $0 [dir|problem|diff]" >&2
    exit 1
    ;;
esac
