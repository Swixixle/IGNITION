"""Defaults for low-friction `ignition start`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ignition import git_ops
from ignition.config import IgnitionConfig
from ignition.decisions import top_level_dirs
from ignition import prompts
from ignition.utils import slugify


def infer_feature_branch_name(task: str, cfg: IgnitionConfig) -> str:
    return f"{cfg.default_feature_branch_prefix}{slugify(task)}"


def infer_scope_from_repo(repo_root: Path, cfg: IgnitionConfig) -> tuple[list[str], str]:
    if cfg.preferred_scope:
        return list(cfg.preferred_scope), "[project].preferred_scope in ignition.toml"
    changed = git_ops.changed_files(repo_root)
    if not changed:
        return [], "no changed files; empty scope"
    dirs = sorted(top_level_dirs(changed))
    scope = [f"{d}/" for d in dirs if d]
    if not scope:
        scope = ["./"]
    return scope, "top-level directories of currently changed paths"


@dataclass
class StartAssumptions:
    task: str
    scope_list: list[str]
    definition: str
    branch_explicit: str | None
    inferred_branch: str | None
    notes: list[str] = field(default_factory=list)

    def add_note(self, s: str) -> None:
        self.notes.append(s)


def resolve_start_inputs(
    repo_root: Path,
    cfg: IgnitionConfig,
    *,
    task: str | None,
    branch: str | None,
    scope_opt: str | None,
    done: str | None,
    yes: bool,
) -> StartAssumptions:
    notes: list[str] = []
    t = task.strip() if task else ""
    if not t and not yes:
        t = prompts.prompt_task()
    if not t:
        raise ValueError("Task name is required.")

    scope_list: list[str]
    if scope_opt is not None and scope_opt.strip():
        scope_list = prompts.split_scope(scope_opt)
        notes.append("Scope from --scope.")
    else:
        scope_list, src = infer_scope_from_repo(repo_root, cfg)
        notes.append(f"Scope: {src}.")

    if done is not None:
        definition = done.strip()
        notes.append("Definition of done from --done.")
    elif yes:
        definition = ""
        notes.append("Definition of done left empty (--yes).")
    else:
        definition = prompts.prompt_definition_of_done()

    inferred = infer_feature_branch_name(t, cfg)
    bex: str | None = branch.strip() if branch else None
    if bex:
        notes.append("Branch from --branch.")
    else:
        notes.append(f"Inferred branch name: {inferred} (not switched yet).")

    return StartAssumptions(
        task=t,
        scope_list=scope_list,
        definition=definition,
        branch_explicit=bex,
        inferred_branch=inferred,
        notes=notes,
    )
