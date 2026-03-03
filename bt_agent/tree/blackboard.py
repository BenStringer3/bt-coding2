from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class StrReplaceEdit(BaseModel):
    old_str: str
    new_str: str
    target_file: str


class AgentBlackboard(BaseModel):
    task_description: str
    repo_path: Path

    parsed_goal: str | None = None
    target_language: str | None = None

    repo_map: str | None = None
    candidate_files: list[str] = Field(default_factory=list)
    selected_file: str | None = None

    edit_plan: str | None = None
    edit_intent: str | None = None

    current_file_content: str | None = None
    proposed_edit: StrReplaceEdit | None = None
    edit_attempts: int = 0
    last_error: str | None = None

    commit_message: str | None = None
    committed: bool = False

    def snapshot(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)


class MultiFileBlackboard(AgentBlackboard):
    """
    Extended blackboard for multi-file editing tasks.

    Adds fields for dependency analysis, per-file context caching,
    snapshot/rollback, and cross-file conflict tracking.
    """

    # Planning phase
    global_plan: str | None = None
    file_edit_queue: list[str] = Field(default_factory=list)
    dependency_graph: dict[str, list[str]] = Field(default_factory=dict)
    symbol_index: dict[str, list[str]] = Field(default_factory=dict)

    # Context phase — populated by LoadAllRelevantFiles / SnapshotCurrentState
    all_file_contents: dict[str, str] = Field(default_factory=dict)
    file_snapshots: dict[str, str] = Field(default_factory=dict)

    # Execution phase
    current_queue_index: int = 0
    file_edits_applied: list[dict] = Field(default_factory=list)
    per_file_plans: dict[str, str] = Field(default_factory=dict)

    # Validation phase
    cross_file_errors: list[str] = Field(default_factory=list)
