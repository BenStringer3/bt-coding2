# BT-Agent (POC)

Behavior-tree based code-editing agent driven by LLM leaf nodes.

## Install

```bash
pip install -e .
```

## Quickstart

```bash
bt-agent run \
  --task "Fix the IndexError in get_pairs" \
  --repo tests/fixtures/off_by_one \
  --dry-run
```

## Notes

- Control flow is deterministic via `py-trees`.
- Edits are applied via `str_replace` and validated with AST syntax checks.
- Every node tick is logged to JSONL trajectory output.
