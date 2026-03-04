---
description: Analyze most recent bt-agent run and write a markdown report
allowed-tools: Bash, Write, Read
argument-hint: [--no-lm-studio]
---

Analyze the most recent bt-agent run log and write a detailed markdown report.

## Collected run log

!`/home/ben/bt_coding2/scripts/run-info.sh log 2>&1`

## Run directory

!`/home/ben/bt_coding2/scripts/run-info.sh dir`

## Problem YAML (task definition)

!`/home/ben/bt_coding2/scripts/run-info.sh problem`

## Agent git diff (changes applied in run dir)

!`/home/ben/bt_coding2/scripts/run-info.sh diff`

---

Using the data above, generate a comprehensive markdown run report and save it as `report.md`
in the run directory shown above (use the Write tool with the full absolute path).

Structure the report as follows:

```
# bt-agent Run Report: <slug> — <OUTCOME>

**Date:** <timestamp>
**Model:** <model name>
**Tree:** <tree type, e.g. run / run-multi>
**Outcome:** SUCCESS ✓ / FAILURE ✗

---

## Summary

1–2 sentence plain-English description of what the agent did and whether it worked.

---

## Behavior Tree Timeline

| Timestamp | Node | Status | Prompt tok | Completion tok | Notes |
|-----------|------|--------|------------|----------------|-------|
| ...       | ...  | ...    | ...        | ...            | ...   |

**Total tokens:** X prompt + Y completion = Z

---

## Model Call Analysis

For each LLM call: which node triggered it, input/output tokens, throughput (tok/s), wall-clock
time. Highlight any calls that were unusually large, slow, or produced excessive thinking tokens.

---

## Changes Applied

Paste or summarize the git diff. Note whether the patch looks correct given the task.

---

## Root Cause Analysis

**For SUCCESS:** What was the root cause of the original bug/task? How did the agent diagnose
it? Was the fix correct and complete, or did it only partially address the problem?

**For FAILURE:** Walk through the failure chain. Which node failed? What error occurred?
Was it a model hallucination, a bad edit, a validation failure, or a tree logic issue?
What would need to change for the run to succeed?

---

## Observations & Anomalies

Anything noteworthy: token efficiency, model self-correction, unexpected node ordering,
performance bottlenecks, incomplete fixes, signs of confusion in the model output, etc.

---

## Recommendations

(Optional) 1–3 concrete suggestions to improve the agent or prompts based on this run.
```

After writing the file, briefly summarize the 3 most interesting findings from this run
in the conversation (2–4 sentences).
