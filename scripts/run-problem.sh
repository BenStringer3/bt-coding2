#!/usr/bin/env bash
# run-problem.sh — pick a fixture problem and launch bt-agent against it
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
VENV_BT_AGENT="$PROJECT_ROOT/.venv/bin/bt-agent"
FIXTURES_DIR="$PROJECT_ROOT/tests/fixtures"
RUNS_DIR="$PROJECT_ROOT/runs"

# ── Pre-flight checks ──────────────────────────────────────────────────────────
if ! command -v fzf &>/dev/null; then
  echo "Error: fzf is not installed. Install it with your package manager." >&2
  exit 1
fi
if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Error: venv not found at $VENV_PYTHON — run: python -m venv .venv && pip install -e ." >&2
  exit 1
fi
if [[ ! -x "$VENV_BT_AGENT" ]]; then
  echo "Error: bt-agent not found at $VENV_BT_AGENT — run: pip install -e ." >&2
  exit 1
fi

# ── Discover fixture problems ──────────────────────────────────────────────────
mapfile -t YAML_FILES < <(find "$FIXTURES_DIR" -name "problem.yaml" | sort)

if [[ ${#YAML_FILES[@]} -eq 0 ]]; then
  echo "Error: no problem.yaml files found under $FIXTURES_DIR" >&2
  exit 1
fi

# Build "slug: Name" display lines
declare -a DISPLAY_LINES
for yaml in "${YAML_FILES[@]}"; do
  slug="$(basename "$(dirname "$yaml")")"
  name="$("$VENV_PYTHON" - "$yaml" <<'EOF'
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
print(data.get("name", ""))
EOF
)"
  DISPLAY_LINES+=("$slug: $name")
done

# ── fzf: pick a problem ────────────────────────────────────────────────────────
CHOSEN=$(printf '%s\n' "${DISPLAY_LINES[@]}" | fzf --prompt="Select problem: " --height=40%)
if [[ -z "$CHOSEN" ]]; then
  echo "Aborted." >&2
  exit 0
fi

SLUG="${CHOSEN%%:*}"
FIXTURE_DIR="$FIXTURES_DIR/$SLUG"
PROBLEM_YAML="$FIXTURE_DIR/problem.yaml"

# ── Parse task and compatible_trees ───────────────────────────────────────────
read -r -d '' PARSE_SCRIPT <<'EOF' || true
import sys, yaml, json
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
print(json.dumps({"task": data["task"], "trees": data.get("compatible_trees", [])}))
EOF

PARSED=$("$VENV_PYTHON" -c "$PARSE_SCRIPT" "$PROBLEM_YAML")
TASK=$(echo "$PARSED" | "$VENV_PYTHON" -c "import sys, json; print(json.load(sys.stdin)['task'])")
mapfile -t TREES < <(echo "$PARSED" | "$VENV_PYTHON" -c "
import sys, json
data = json.load(sys.stdin)
for t in data['trees']:
    print(t)
")

# ── fzf or auto-select tree ────────────────────────────────────────────────────
if [[ ${#TREES[@]} -eq 1 ]]; then
  TREE="${TREES[0]}"
  echo "Tree: $TREE (only compatible option)"
else
  TREE=$(printf '%s\n' "${TREES[@]}" | fzf --prompt="Select tree: " --height=20%)
  if [[ -z "$TREE" ]]; then
    echo "Aborted." >&2
    exit 0
  fi
fi

# ── Create run directory ───────────────────────────────────────────────────────
TS=$(date +"%Y%m%d-%H%M%S")
RUN_DIR="$RUNS_DIR/${SLUG}-${TS}"
mkdir -p "$RUN_DIR"

# Copy fixture files (excluding problem.yaml)
find "$FIXTURE_DIR" -maxdepth 1 -type f ! -name "problem.yaml" -exec cp {} "$RUN_DIR/" \;

# Init git repo in run dir
(cd "$RUN_DIR" && git init -q && git add . && git commit -q -m "Initial state: $SLUG")

TRAJECTORY="$RUN_DIR/trajectory.jsonl"

# ── Launch bt-agent ────────────────────────────────────────────────────────────
echo "Running: bt-agent $TREE"
echo "  Repo:  $RUN_DIR"
echo "  Task:  $TASK"
echo ""

set +e
"$VENV_BT_AGENT" "$TREE" \
  --task "$TASK" \
  --repo "$RUN_DIR" \
  --output "$TRAJECTORY"
EXIT_CODE=$?
set -e

echo ""
echo "Trajectory log: $TRAJECTORY"
if [[ $EXIT_CODE -ne 0 ]]; then
  echo "Note: bt-agent exited with code $EXIT_CODE — log may contain partial run."
fi
