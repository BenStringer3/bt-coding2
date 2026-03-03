from __future__ import annotations

from pathlib import Path

import git


def stage_and_commit(repo_path: Path, file_path: str, message: str) -> tuple[bool, str]:
    try:
        repo = git.Repo(repo_path)
    except git.exc.InvalidGitRepositoryError:
        return False, "Not a git repository"

    try:
        repo.index.add([file_path])
        staged_diff = repo.index.diff("HEAD") if repo.head.is_valid() else repo.index.diff(None)
        if not staged_diff and not repo.untracked_files:
            return False, "Nothing to commit"
        repo.index.commit(message)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def stage_and_commit_all(
    repo_path: Path, file_paths: list[str], message: str
) -> tuple[bool, str]:
    """Stage multiple files and create a single commit."""
    try:
        repo = git.Repo(repo_path)
    except git.exc.InvalidGitRepositoryError:
        return False, "Not a git repository"

    try:
        repo.index.add(file_paths)
        staged_diff = repo.index.diff("HEAD") if repo.head.is_valid() else repo.index.diff(None)
        if not staged_diff and not repo.untracked_files:
            return False, "Nothing to commit"
        repo.index.commit(message)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
