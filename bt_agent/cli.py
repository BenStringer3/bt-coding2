from __future__ import annotations

import difflib
import logging
import os
import json
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import click
import dotenv
import git
import py_trees
import yaml
from rich.console import Console

from bt_agent.llm.client import LLMClient
from bt_agent.logging.trajectory import TrajectoryLogger
from bt_agent.tree.blackboard import AgentBlackboard, MultiFileBlackboard
from bt_agent.tree.builder import build_tree
from bt_agent.tree.multifile_builder import build_multifile_tree

dotenv.load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
console = Console()


def _load_config() -> dict:
    cfg_path = Path("config/default.yaml")
    if not cfg_path.exists():
        return {}
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}


def _show_diff(repo_path: Path) -> None:
    try:
        repo = git.Repo(repo_path)
        diff_text = repo.git.diff("HEAD") if repo.head.is_valid() else repo.git.diff()
        if not diff_text and repo.head.is_valid():
            # If changes were committed, show the last commit patch.
            try:
                diff_text = repo.git.show("--format=", "HEAD")
            except Exception:  # noqa: BLE001
                diff_text = ""
        if diff_text:
            console.print("\n[bold]Diff:[/bold]")
            console.print(diff_text)
            return
    except Exception:  # noqa: BLE001
        pass

    py_files = sorted(repo_path.rglob("*.py"))
    if not py_files:
        return
    # Fallback unified diff from working files to themselves is empty; this is only best-effort.
    before = []
    after = []
    for path in py_files:
        text = path.read_text(encoding="utf-8").splitlines(keepends=True)
        before.extend(text)
        after.extend(text)
    diff = "".join(difflib.unified_diff(before, after, fromfile="before", tofile="after"))
    if diff:
        console.print(diff)


def _preflight_ollama(model: str) -> None:
    if not model.startswith("ollama/"):
        return
    model_name = model.split("/", 1)[1]
    try:
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=2.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except URLError as exc:
        raise click.ClickException(
            "Ollama preflight failed: cannot reach http://127.0.0.1:11434. "
            "Start Ollama (e.g. `ollama serve`) and retry."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"Ollama preflight failed: {exc}") from exc

    models = {m.get("name", "") for m in payload.get("models", []) if isinstance(m, dict)}
    if model_name not in models:
        raise click.ClickException(
            f"Ollama model '{model_name}' is not available locally. "
            f"Run `ollama pull {model_name}` and retry."
        )


@click.group()
def cli() -> None:
    """Behavior-tree code editing agent."""


@cli.command()
@click.option("--task", "task_description", required=True, help="Plain-English coding task")
@click.option("--repo", "repo_path", required=True, type=click.Path(path_type=Path, exists=True, file_okay=False))
@click.option("--model", default=None, help="LLM model (overrides config and BT_AGENT_MODEL)")
@click.option("--output", "output_path", default=Path("trajectory.jsonl"), type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True, default=False, help="Skip git commit")
@click.option("--max-attempts", default=None, type=int, help="Max edit retries")
@click.option("--verbose", is_flag=True, default=False, help="Print blackboard state after run")
def run(task_description: str, repo_path: Path, model: str | None, output_path: Path, dry_run: bool, max_attempts: int | None, verbose: bool) -> None:
    cfg = _load_config()
    chosen_model = model or os.getenv("BT_AGENT_MODEL") or cfg.get("model", "ollama/qwen2.5-coder:7b")
    temperature = float(cfg.get("temperature", 0.0))
    max_tokens = int(cfg.get("max_tokens", 2048))
    attempts = max_attempts if max_attempts is not None else int(cfg.get("max_edit_attempts", 5))
    _preflight_ollama(chosen_model)

    try:
        repo = git.Repo(repo_path)
        if repo.is_dirty(untracked_files=True):
            console.print("[yellow]Warning: repository has uncommitted changes.[/yellow]")
    except Exception:  # noqa: BLE001
        console.print("[yellow]Warning: repository is not a valid git repo.[/yellow]")

    bb = AgentBlackboard(task_description=task_description, repo_path=repo_path)
    llm = LLMClient(model=chosen_model, temperature=temperature, max_tokens=max_tokens)
    root = build_tree(bb, llm, dry_run=dry_run, max_attempts=attempts)
    tree = py_trees.trees.BehaviourTree(root)

    logger_visitor = TrajectoryLogger(output_path=output_path, blackboard=bb)
    tree.visitors.append(logger_visitor)

    console.print("[bold]Behavior Tree[/bold]")
    console.print(py_trees.display.ascii_tree(root))

    tick_count = 0
    while root.status == py_trees.common.Status.RUNNING or tick_count == 0:
        tree.tick()
        tick_count += 1

    status = root.status.name
    color = "green" if root.status == py_trees.common.Status.SUCCESS else "red"
    console.print(f"[{color}]Final status: {status}[/{color}]")

    if verbose:
        console.print(bb.model_dump_json(indent=2))

    _show_diff(repo_path)
    logger_visitor.close()


@cli.command(name="run-multi")
@click.option("--task", "task_description", required=True, help="Plain-English coding task")
@click.option("--repo", "repo_path", required=True, type=click.Path(path_type=Path, exists=True, file_okay=False))
@click.option("--model", default=None, help="LLM model (overrides config and BT_AGENT_MODEL)")
@click.option("--output", "output_path", default=Path("trajectory_multi.jsonl"), type=click.Path(path_type=Path))
@click.option("--dry-run", is_flag=True, default=False, help="Skip git commit")
@click.option("--verbose", is_flag=True, default=False, help="Print blackboard state after run")
def run_multi(
    task_description: str,
    repo_path: Path,
    model: str | None,
    output_path: Path,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Multi-file behavior-tree editing agent."""
    cfg = _load_config()
    chosen_model = model or os.getenv("BT_AGENT_MODEL") or cfg.get("model", "ollama/qwen2.5-coder:7b")
    temperature = float(cfg.get("temperature", 0.0))
    max_tokens = int(cfg.get("max_tokens", 2048))
    _preflight_ollama(chosen_model)

    try:
        repo = git.Repo(repo_path)
        if repo.is_dirty(untracked_files=True):
            console.print("[yellow]Warning: repository has uncommitted changes.[/yellow]")
    except Exception:  # noqa: BLE001
        console.print("[yellow]Warning: repository is not a valid git repo.[/yellow]")

    bb = MultiFileBlackboard(task_description=task_description, repo_path=repo_path)
    llm = LLMClient(model=chosen_model, temperature=temperature, max_tokens=max_tokens)
    root = build_multifile_tree(bb, llm, dry_run=dry_run)
    tree = py_trees.trees.BehaviourTree(root)

    logger_visitor = TrajectoryLogger(output_path=output_path, blackboard=bb)
    tree.visitors.append(logger_visitor)

    console.print("[bold]Multi-File Behavior Tree[/bold]")
    console.print(py_trees.display.ascii_tree(root))

    tick_count = 0
    while root.status == py_trees.common.Status.RUNNING or tick_count == 0:
        tree.tick()
        tick_count += 1

    status = root.status.name
    color = "green" if root.status == py_trees.common.Status.SUCCESS else "red"
    console.print(f"[{color}]Final status: {status}[/{color}]")

    if bb.file_edit_queue:
        console.print(f"[cyan]Files edited: {', '.join(bb.file_edit_queue)}[/cyan]")
    if bb.cross_file_errors:
        console.print("[yellow]Cross-file validation errors:[/yellow]")
        for err in bb.cross_file_errors:
            console.print(f"  [yellow]• {err}[/yellow]")

    if verbose:
        console.print(bb.model_dump_json(indent=2))

    _show_diff(repo_path)
    logger_visitor.close()


if __name__ == "__main__":
    cli()
