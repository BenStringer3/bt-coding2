#!/usr/bin/env bash
# collect-logs.sh — read the most recent trajectory.jsonl in human-readable form,
#                   optionally interleaved with LM Studio server logs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"

RUNS_DIR="$PROJECT_ROOT/runs"
LM_STUDIO_LOG=""
LM_STUDIO_LOGS_DIR="$HOME/.lmstudio/server-logs"

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --runs-dir)
      RUNS_DIR="$2"
      shift 2
      ;;
    --lm-studio-log)
      LM_STUDIO_LOG="$2"
      shift 2
      ;;
    --no-lm-studio)
      LM_STUDIO_LOGS_DIR=""
      shift
      ;;
    *)
      echo "Usage: $0 [--runs-dir <path>] [--lm-studio-log <path>] [--no-lm-studio]" >&2
      exit 1
      ;;
  esac
done

# ── Find most recent trajectory.jsonl ─────────────────────────────────────────
TRAJECTORY=""
if [[ -d "$RUNS_DIR" ]]; then
  TRAJECTORY=$(find "$RUNS_DIR" -name "trajectory.jsonl" | sort -r | head -1)
fi

# Fallback: trajectory.jsonl in current directory
if [[ -z "$TRAJECTORY" && -f "trajectory.jsonl" ]]; then
  TRAJECTORY="$(pwd)/trajectory.jsonl"
fi

if [[ -z "$TRAJECTORY" ]]; then
  echo "Error: no trajectory.jsonl found under $RUNS_DIR" >&2
  echo "Run a problem first with scripts/run-problem.sh, or pass --runs-dir <path>" >&2
  exit 1
fi

# ── Auto-discover LM Studio log ───────────────────────────────────────────────
if [[ -z "$LM_STUDIO_LOG" && -n "$LM_STUDIO_LOGS_DIR" && -d "$LM_STUDIO_LOGS_DIR" ]]; then
  LM_STUDIO_LOG=$(find "$LM_STUDIO_LOGS_DIR" -name "*.log" | sort -r | head -1)
fi

echo "Reading: $TRAJECTORY"
if [[ -n "$LM_STUDIO_LOG" ]]; then
  echo "LM Studio: $LM_STUDIO_LOG"
fi
echo ""

# ── Process with inline Python ────────────────────────────────────────────────
"$VENV_PYTHON" - "$TRAJECTORY" "${LM_STUDIO_LOG:-}" <<'EOF'
import sys
import json
import re

traj_path = sys.argv[1]
lm_log_path = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None

# ── Parse trajectory ──────────────────────────────────────────────────────────
traj_entries = []
with open(traj_path) as f:
    for lineno, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        try:
            traj_entries.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"  [warn] line {lineno} malformed, skipping: {e}", file=sys.stderr)

# Find last run start: scan backward for UnderstandTask or BuildRepoMap
RUN_START_NODES = {"UnderstandTask", "BuildRepoMap"}
run_start_idx = 0
for i in range(len(traj_entries) - 1, -1, -1):
    if traj_entries[i].get("node") in RUN_START_NODES:
        run_start_idx = i
        break

run_entries = traj_entries[run_start_idx:]
if not run_entries:
    print("No run entries found in trajectory.")
    sys.exit(0)

def norm_ts(ts):
    """Normalise ISO or bracket timestamp to sortable YYYY-MM-DD HH:MM:SS."""
    return ts.replace("T", " ").split(".")[0]

run_start_ts = norm_ts(run_entries[0].get("timestamp", ""))

# Build event list from trajectory: (ts, source_order, data)
# source_order controls tie-breaking within the same second:
#   0 = lm_request  1 = lm_response  2 = traj
events = []
for entry in run_entries:
    ts = norm_ts(entry.get("timestamp", "?"))
    events.append((ts, 2, entry))

# ── Parse LM Studio log ───────────────────────────────────────────────────────
if lm_log_path:
    LMS_RE = re.compile(
        r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\[(\w+)\](?:\[([^\]]+)\])? (.*)'
    )

    # Group raw lines into logical entries
    lm_entries = []
    cur = None
    with open(lm_log_path) as f:
        for line in f:
            line = line.rstrip()
            m = LMS_RE.match(line)
            if m:
                if cur:
                    lm_entries.append(cur)
                cur = {
                    "ts": m.group(1),
                    "level": m.group(2),
                    "model": m.group(3),
                    "lines": [m.group(4)],
                }
            elif cur:
                cur["lines"].append(line)
    if cur:
        lm_entries.append(cur)

    # Extract interesting events; filter to current run's time window
    pending_timing = {}
    for e in lm_entries:
        if e["ts"] < run_start_ts:
            continue
        text = e["lines"][0]
        full = "\n".join(e["lines"])

        if "Received request: POST to /v1/chat/completions" in text:
            try:
                body_str = full[full.index("with body ") + 10:]
                body = json.loads(body_str)
                events.append((e["ts"], 0, {
                    "_kind": "lm_request",
                    "model": body.get("model", "?"),
                    "n_msgs": len(body.get("messages", [])),
                }))
            except Exception:
                events.append((e["ts"], 0, {
                    "_kind": "lm_request",
                    "model": "?",
                    "n_msgs": "?",
                }))

        elif "slot print_timing" in text:
            timing = {}
            for line in e["lines"][1:]:
                # "       eval time =    7196.33 ms /   548 tokens (...  76.15 tokens per second)"
                if re.match(r"\s+eval time", line):
                    m2 = re.search(r"([\d.]+) tokens per second", line)
                    if m2:
                        timing["tok_per_sec"] = float(m2.group(1))
                    m2 = re.search(r"eval time\s+=\s+([\d.]+) ms\s*/\s*(\d+) tokens", line)
                    if m2:
                        timing["eval_tokens"] = int(m2.group(2))
                elif "total time" in line:
                    m2 = re.search(r"total time\s+=\s+([\d.]+) ms", line)
                    if m2:
                        timing["total_ms"] = float(m2.group(1))
            pending_timing = timing

        elif "Generated prediction:" in text and e["level"] == "INFO":
            data = {"_kind": "lm_response"}
            data.update(pending_timing)
            pending_timing = {}
            try:
                pred_str = full[full.index("Generated prediction:") + 21:].strip()
                pred = json.loads(pred_str)
                usage = pred.get("usage", {})
                data["prompt_tokens"] = usage.get("prompt_tokens")
                data["completion_tokens"] = usage.get("completion_tokens")
                choices = pred.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    think_end = content.find("</think>")
                    if think_end != -1:
                        content = content[think_end + 8:].strip()
                    data["snippet"] = content[:120]
            except Exception:
                pass
            events.append((e["ts"], 1, data))

# ── Sort: by timestamp, then by source_order for same-second ties ─────────────
events.sort(key=lambda e: (e[0], e[1]))

# ── Display ───────────────────────────────────────────────────────────────────
for ts, _order, data in events:
    kind = data.get("_kind") if isinstance(data, dict) else None

    if kind == "lm_request":
        model = data.get("model", "?")
        n_msgs = data.get("n_msgs", "?")
        print(f"[{ts}] ▶ LM request   model={model}  {n_msgs} messages")

    elif kind == "lm_response":
        parts = []
        pt = data.get("prompt_tokens")
        ct = data.get("completion_tokens")
        if pt is not None and ct is not None:
            parts.append(f"{pt}+{ct} tokens")
        tok_per_sec = data.get("tok_per_sec")
        if tok_per_sec is not None:
            parts.append(f"{tok_per_sec:.1f} tok/s")
        total_ms = data.get("total_ms")
        if total_ms is not None:
            parts.append(f"{total_ms / 1000:.1f}s")
        print(f"[{ts}] ◀ LM response  {'  '.join(parts)}")
        snippet = data.get("snippet", "")
        if snippet:
            ellipsis = "…" if len(data.get("snippet", "")) >= 120 else ""
            print(f"  {snippet}{ellipsis}")

    else:
        # Trajectory entry
        entry = data
        node = entry.get("node", "?")
        status = entry.get("status", "?")
        llm = entry.get("llm_call") or {}
        thought = llm.get("thought", "")
        prompt_tokens = llm.get("prompt_tokens")
        completion_tokens = llm.get("completion_tokens")
        error = entry.get("error", "")

        token_parts = []
        if prompt_tokens is not None:
            token_parts.append(f"{prompt_tokens} prompt")
        if completion_tokens is not None:
            token_parts.append(f"{completion_tokens} completion tokens")
        token_suffix = f"  ({' + '.join(token_parts)})" if token_parts else ""

        print(f"[{ts}] {node} → {status}{token_suffix}")

        if thought:
            print("  <think>")
            for line in thought.splitlines():
                print(f"  {line}")
            print("  </think>")

        if error:
            print(f"  ERROR: {error}")

EOF
