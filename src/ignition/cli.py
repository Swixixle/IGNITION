"""IGNITION CLI: start, checkpoint, status, stop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from ignition import __version__
from ignition import git_ops
from ignition import carryforward as carryforward_mod
from ignition import bootstrap as bootstrap_mod
from ignition import current_cmd as current_cmd_mod
from ignition import hooks as hooks_mod
from ignition import inference as inference_mod
from ignition import stale as stale_mod
from ignition.checkpoint import make_checkpoint_record
from ignition.config import load_config
from ignition import decisions as decisions_mod
from ignition import explain as explain_mod
from ignition import doctor as doctor_mod
from ignition import export_import as export_import_mod
from ignition import handoff as handoff_mod
from ignition import hygiene as hygiene_mod
from ignition import listing as listing_mod
from ignition import notes_tags
from ignition import ready as ready_mod
from ignition import timeline as timeline_mod
from ignition.normalize import wip_like_commit_count
from ignition import phrasing
from ignition.json_output import json_envelope
from ignition.paths import exports_dir, receipt_dir
from ignition import receipts as receipts_mod
from ignition import review as review_mod
from ignition import resume as resume_mod
from ignition import session as session_mod
from ignition import trends as trends_mod
from ignition import linkage as linkage_mod
from ignition import status as status_mod
from ignition import summary as summary_mod
from ignition import terminal_ux as ux_mod
from ignition.tests import run_test_command
from ignition import prompts
from ignition.utils import (
    parse_iso_duration_minutes,
    scope_in_out_counts,
    top_out_of_scope,
    utc_now_iso,
)


def _enforce_start_guardrails(repo_root: Path, cfg, *, force: bool, yes: bool) -> None:
    """Block duplicate active sessions unless --force; cross-branch needs confirm or --force."""
    if session_mod.pointer_repo_mismatch(repo_root, cfg.session_dir) and not force:
        typer.secho(
            "current_session.json points at another clone (different repo root). "
            "Work in that directory to continue, or use --force if you intend to start fresh here.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    active_sp = session_mod.read_active_session_file(repo_root, cfg.session_dir)
    if not active_sp or force:
        return
    data = session_mod.load_session_soft(active_sp)
    if data is None:
        return
    if not session_mod.is_session_unfinished(data):
        return
    cur = git_ops.get_current_branch(repo_root)
    sess_br = data.get("branch") or ""
    sid = data.get("session_id", "")
    if sess_br == cur:
        typer.secho(
            f"An active session already exists (`{sid}` on branch `{cur}`). "
            "Run `ignition resume` to continue it or `ignition stop` to end it. "
            "To start another session anyway, use --force.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    typer.secho(
        f"Unfinished session `{sid}` was for branch `{sess_br}`; you are on `{cur}`.",
        fg=typer.colors.YELLOW,
        err=True,
    )
    if yes and not force:
        typer.secho(
            "Refusing while another branch's session is active. Pass --force to start anyway.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)
    if not typer.confirm("Start a new session on the current branch anyway?", default=False):
        raise typer.Exit(1)


def _pointer_stale(repo_root: Path, cfg) -> bool:
    raw = session_mod.read_active_pointer_raw(repo_root, cfg.session_dir)
    if not raw:
        return False
    sf = raw.get("session_file", "")
    return bool(sf) and not Path(sf).is_file()


def _version_cb(value: bool) -> None:
    if value:
        typer.echo(f"ignition {__version__}")
        raise typer.Exit(0)


app = typer.Typer(
    name="ignition",
    no_args_is_help=True,
    help="Session-control CLI for bounded, auditable coding work.",
)


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option("--version", "-V", callback=_version_cb, is_eager=True),
    ] = False,
) -> None:
    return


@app.command("init")
def cmd_init() -> None:
    """Create ignition.toml and data directories with sensible defaults (does not edit shell rc)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    res = bootstrap_mod.run_init(repo_root, cfg.session_dir, cfg.receipt_dir, cfg.templates_dir)

    ux_mod.section_header("IGNITION init")
    typer.echo(f"Repository: {res.repo_name} ({repo_root})")
    typer.echo(f"Default branch (detected): {res.default_branch}")
    if res.created_config:
        typer.secho(f"Created {res.config_path}", fg=typer.colors.GREEN)
    else:
        typer.echo(f"Config already exists: {res.config_path} (left unchanged)")
    typer.echo(f"Session dir:  {res.session_dir}")
    typer.echo(f"Receipt dir:  {res.receipt_dir}")
    typer.echo(f"Templates dir: {res.templates_dir}")
    if res.suggested_test:
        typer.echo(f"Suggested test command (also embedded if this was a new config): {res.suggested_test}")
    else:
        typer.echo("No test command auto-detected; set auto_checkpoint_test_command in ignition.toml if you want.")
    typer.echo("")
    typer.echo(bootstrap_mod.shell_init_snippet("zsh"))
    typer.echo("Next: ignition start --task \"…\"   or   ignition hook print --shell zsh")


@app.command("start")
def cmd_start(
    task: Annotated[str | None, typer.Option("--task", "-t", help="Task name")] = None,
    branch: Annotated[str | None, typer.Option("--branch", "-b", help="Feature branch name")] = None,
    scope: Annotated[
        str | None,
        typer.Option("--scope", "-s", help="Comma-separated paths or globs"),
    ] = None,
    done: Annotated[
        str | None,
        typer.Option("--done", "-d", help="Definition of done"),
    ] = None,
    no_branch_switch: Annotated[
        bool,
        typer.Option("--no-branch-switch", help="Do not create/switch branch"),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Accept defaults; non-interactive (requires --task)"),
    ] = False,
    print_assumptions: Annotated[
        bool,
        typer.Option("--print-assumptions", help="Print inferred defaults"),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Start even if another active session exists"),
    ] = False,
) -> None:
    """Begin a session: capture context, optional feature branch, session record."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    _enforce_start_guardrails(repo_root, cfg, force=force, yes=yes)

    porcelain = git_ops.status_porcelain(repo_root)
    dirty = bool(porcelain.strip())

    if dirty:
        on_default = git_ops.get_current_branch(repo_root) == cfg.default_branch
        if on_default:
            typer.secho(
                f"Warning: uncommitted changes while on '{cfg.default_branch}'.",
                fg=typer.colors.YELLOW,
            )
        if yes:
            res = "keep"
        else:
            res = prompts.prompt_dirty_resolution()
        if res == "abort":
            typer.echo("Aborted.")
            raise typer.Exit(1)
        if res == "stash":
            try:
                git_ops.stash_push(repo_root, "ignition: stash before session start")
            except git_ops.GitError as e:
                typer.secho(str(e), fg=typer.colors.RED, err=True)
                raise typer.Exit(1)

    if yes and not (task and task.strip()):
        typer.secho("--yes requires --task.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    try:
        assumptions = inference_mod.resolve_start_inputs(
            repo_root,
            cfg,
            task=task,
            branch=branch,
            scope_opt=scope,
            done=done,
            yes=yes,
        )
    except ValueError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if not yes and not assumptions.scope_list:
        assumptions.scope_list = prompts.prompt_scope_list()

    if print_assumptions:
        for line in assumptions.notes:
            typer.echo(f"Assumption: {line}")

    t = assumptions.task
    scope_list = assumptions.scope_list
    definition = assumptions.definition

    current = git_ops.get_current_branch(repo_root)
    explicit_branch = assumptions.branch_explicit
    inferred = assumptions.inferred_branch or inference_mod.infer_feature_branch_name(t, cfg)

    if not no_branch_switch:
        if current == cfg.default_branch:
            target = explicit_branch or inferred
            if target:
                try:
                    git_ops.switch_or_create_branch(repo_root, target)
                except git_ops.GitError as e:
                    typer.secho(str(e), fg=typer.colors.RED, err=True)
                    raise typer.Exit(1)
        elif explicit_branch and explicit_branch != current:
            try:
                git_ops.switch_or_create_branch(repo_root, explicit_branch)
            except git_ops.GitError as e:
                typer.secho(str(e), fg=typer.colors.RED, err=True)
                raise typer.Exit(1)

    branch_name = git_ops.get_current_branch(repo_root)
    initial_head = git_ops.head_hash(repo_root)
    initial_status = git_ops.status_porcelain(repo_root)
    wt = git_ops.is_linked_worktree(repo_root)
    default_br = git_ops.detect_default_branch(repo_root)

    session_id, session_path = session_mod.create_session_record(
        repo_root,
        cfg.session_dir,
        cfg.receipt_dir,
        repo_name=repo_root.name,
        branch=branch_name,
        task=t,
        scope=scope_list,
        definition_of_done=definition,
        initial_git_status=initial_status,
        initial_head=initial_head,
        worktree_path=str(repo_root.resolve()),
        is_worktree=wt,
        repo_default_branch=default_br,
    )

    rdir = receipt_dir(repo_root, cfg.receipt_dir)
    md_path = rdir / f"{session_id}.md"
    json_path = rdir / f"{session_id}.json"

    stub = {
        "session": {
            "session_id": session_id,
            "repo_name": repo_root.name,
            "repo_root": str(repo_root.resolve()),
            "branch": branch_name,
            "task": t,
            "scope": scope_list,
            "definition_of_done": definition,
            "started_at": utc_now_iso(),
            "ended_at": None,
        },
        "phase": "started",
    }
    receipts_mod.write_json_receipt(json_path, stub)
    receipts_mod.write_markdown_receipt(md_path, {**stub, "files_changed": [], "files_changed_count": 0, "diff_stat_session": "", "commits_during_session": [], "test_result": None, "final_status": "active", "suggested_next_action": "Work; use `ignition checkpoint` and `ignition stop` when done.", "cleanup_suggestions": []})  # noqa: E501

    sess = session_mod.load_session(session_path)
    sess["receipt_json"] = str(json_path)
    sess["receipt_md"] = str(md_path)
    session_mod.save_session(session_path, sess)

    typer.secho(f"Session started: {session_id}", fg=typer.colors.GREEN)
    typer.echo(f"  Branch: {branch_name}")
    typer.echo(f"  Record:  {session_path}")
    typer.echo(f"  Receipt: {md_path}")


@app.command("begin")
def cmd_begin(
    ctx: typer.Context,
    task: Annotated[str | None, typer.Option("--task", "-t", help="Task name")] = None,
    branch: Annotated[str | None, typer.Option("--branch", "-b", help="Feature branch name")] = None,
    scope: Annotated[str | None, typer.Option("--scope", "-s", help="Comma-separated paths or globs")] = None,
    done: Annotated[str | None, typer.Option("--done", "-d", help="Definition of done")] = None,
    no_branch_switch: Annotated[bool, typer.Option("--no-branch-switch", help="Do not create/switch branch")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Accept defaults; non-interactive (requires --task)")] = False,
    force: Annotated[bool, typer.Option("--force", help="Start even if unfinished session on branch")] = False,
) -> None:
    """Fast path into a session: resume if needed, else like `start` with assumptions printed."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    cur = git_ops.get_current_branch_safe(repo_root)
    if cur != "(unknown)":
        _un_path, un_data = resume_mod.unfinished_on_branch(repo_root, cfg.session_dir, cur)
        if un_data is not None and not force:
            typer.secho(
                f"You already have an unfinished session on `{cur}` (`{un_data.get('session_id')}`). "
                "Run `ignition resume` to continue it, or `ignition begin --force` to start a new one.",
                fg=typer.colors.YELLOW,
                err=True,
            )
            raise typer.Exit(1)

    prior_payload = carryforward_mod.build_next_payload(repo_root, cfg, branch=cur if cur != "(unknown)" else None)
    if prior_payload.get("prior_session_id"):
        ux_mod.section_header("Where you left off")
        typer.echo(carryforward_mod.format_next_human(prior_payload, plain=cfg.plain_language))

    ctx.invoke(
        cmd_start,
        task=task,
        branch=branch,
        scope=scope,
        done=done,
        no_branch_switch=no_branch_switch,
        yes=yes,
        print_assumptions=True,
        force=force,
    )

    sp = session_mod.read_active_session_file(repo_root, cfg.session_dir)
    if not sp:
        return
    br2 = git_ops.get_current_branch_safe(repo_root)
    prior = carryforward_mod.find_latest_stopped_session(
        repo_root,
        cfg.session_dir,
        branch=None if br2 == "(unknown)" else br2,
    )
    data = session_mod.load_session(sp)
    if prior and prior.get("session_id") != data.get("session_id"):
        session_mod.merge_session_update(
            sp,
            {"carryforward_inherited": carryforward_mod.inherited_block_from_prior(prior)},
        )


@app.command("next")
def cmd_next(
    branch: Annotated[str | None, typer.Option("--branch", "-b", help="Filter by branch")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Short view of carry-forward from the last stopped session (this branch by default)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    payload = carryforward_mod.build_next_payload(repo_root, cfg, branch=branch)
    if as_json:
        typer.echo(json.dumps(json_envelope(payload, repo_root=repo_root), indent=2))
        return
    ux_mod.section_header("Next")
    typer.echo(carryforward_mod.format_next_human(payload, plain=cfg.plain_language))


@app.command("amend-context")
def cmd_amend_context(
    session_id: Annotated[str | None, typer.Option("--session-id", help="Session to edit (default: active)")] = None,
    task: Annotated[str | None, typer.Option("--task", "-t")] = None,
    scope: Annotated[str | None, typer.Option("--scope", "-s", help="Comma-separated; replaces scope")] = None,
    done: Annotated[str | None, typer.Option("--done", "-d", help="Definition of done")] = None,
    carryforward_summary: Annotated[str | None, typer.Option("--summary", help="Short carry-forward blurb")] = None,
    todo: Annotated[str | None, typer.Option("--todo", help="Append one todo line")] = None,
    risk: Annotated[str | None, typer.Option("--risk")] = None,
    question: Annotated[str | None, typer.Option("--question")] = None,
    followup: Annotated[str | None, typer.Option("--followup")] = None,
) -> None:
    """Update task/scope/carry-forward fields on the active session (or a specific id)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    if session_id:
        sp = session_mod.session_file_path(repo_root, cfg.session_dir, session_id)
        if not sp.is_file():
            typer.secho(f"No session `{session_id}`.", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)
    else:
        sp = session_mod.read_active_session_file(repo_root, cfg.session_dir)
        if not sp:
            typer.secho("No active session.", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)

    data = session_mod.load_session(sp)
    if data.get("status") == "stopped":
        typer.secho("Session is stopped; use a new session instead.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if task is not None:
        data["task"] = task.strip()
    if scope is not None:
        data["scope"] = prompts.split_scope(scope)
    if done is not None:
        data["definition_of_done"] = done.strip()
    if carryforward_summary is not None:
        data["carryforward_summary"] = carryforward_summary.strip()
    for val, target in (
        (todo, "carryforward_todos"),
        (risk, "carryforward_risks"),
        (question, "carryforward_questions"),
        (followup, "carryforward_followups"),
    ):
        if val:
            data.setdefault(target, []).append(val.strip())
    session_mod.save_session(sp, data)
    typer.secho(f"Updated {sp.name}", fg=typer.colors.GREEN)


@app.command("checklist")
def cmd_checklist() -> None:
    """Print merge checklist from config plus light session reminders."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    items = list(cfg.merge_checklist)
    if cfg.review_command:
        items.append(f"Run review/tests: {cfg.review_command}")

    sp = session_mod.read_active_session_file(repo_root, cfg.session_dir)
    if sp:
        s = session_mod.load_session(sp)
        if s.get("carryforward_todos"):
            items.append(f"Open todos noted: {len(s['carryforward_todos'])} item(s)")
        if s.get("carryforward_risks"):
            items.append("Unresolved risks noted in session")

    ux_mod.section_header("Checklist")
    if not items:
        typer.echo("(No merge_checklist in ignition.toml — add [project].merge_checklist.)")
        return
    for i, line in enumerate(items, 1):
        typer.echo(f"  {i}. {line}")


@app.command("checkpoint")
def cmd_checkpoint(
    note: Annotated[str | None, typer.Option("--note", "-n", help="Checkpoint note")] = None,
    action: Annotated[
        str | None,
        typer.Option("--action", "-a", help="wip | stash | note"),
    ] = None,
    run_tests: Annotated[
        bool,
        typer.Option("--test/--no-test", help="Run configured test command"),
    ] = True,
) -> None:
    """Create a recovery point: diff summary, optional WIP commit or stash."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    sp = session_mod.read_active_session_file(repo_root, cfg.session_dir)
    if not sp:
        typer.secho("No active session. Run `ignition start` first.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    session = session_mod.load_session(sp)
    changed = git_ops.changed_files(repo_root)
    dstat = git_ops.diff_stat(repo_root)

    tr = None
    tr_dict = None
    if run_tests and cfg.auto_checkpoint_test_command:
        typer.echo(f"Running tests: {cfg.auto_checkpoint_test_command}")
        tr = run_test_command(repo_root, cfg.auto_checkpoint_test_command)
        tr_dict = summary_mod.test_result_to_dict(tr)
        if tr.skipped:
            typer.echo("(Tests skipped — not configured.)")
        else:
            typer.echo(f"Tests exit code: {tr.exit_code}")

    act = (action or "").lower().strip() or prompts.prompt_checkpoint_action()
    wip_hash = None
    stash_msg = None
    if act == "wip":
        msg = note or f"wip: checkpoint ({session.get('task', 'session')})"
        try:
            wip_hash = git_ops.commit_all(repo_root, msg)
            typer.secho(f"WIP commit: {wip_hash}", fg=typer.colors.GREEN)
        except git_ops.GitError as e:
            typer.secho(str(e), fg=typer.colors.RED, err=True)
    elif act == "stash":
        stash_msg = note or f"wip: ignition checkpoint — {session.get('task', 'session')}"
        try:
            git_ops.stash_push(repo_root, stash_msg)
            typer.secho("Stashed.", fg=typer.colors.GREEN)
        except git_ops.GitError as e:
            typer.secho(str(e), fg=typer.colors.RED, err=True)

    note_text = note or ""
    if act == "note" and not note_text:
        note_text = typer.prompt("Note (optional)", default="").strip()

    tag_map = notes_tags.parse_note_tags(note_text)
    rec = make_checkpoint_record(
        changed_files=changed,
        diff_stat=dstat,
        test_result=tr_dict,
        wip_commit_hash=wip_hash,
        stash_message=stash_msg,
        note=note_text,
        head_hash=git_ops.head_hash(repo_root),
        note_tags=tag_map,
    )
    session_mod.append_checkpoint(sp, rec)
    typer.echo("Checkpoint recorded.")


@app.command("current")
def cmd_current(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
) -> None:
    """Show the active session in one short block (or say if none)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    sp = session_mod.read_active_session_file(repo_root, cfg.session_dir)
    if not sp:
        out = {
            "active": False,
            "repo_root": str(repo_root.resolve()),
            "branch": git_ops.get_current_branch_safe(repo_root),
        }
        if as_json:
            typer.echo(json.dumps(json_envelope(out, repo_root=repo_root), indent=2))
            return
        ux_mod.section_header("IGNITION")
        typer.secho("No active session.", fg=typer.colors.YELLOW)
        typer.echo(f"Repo: {repo_root.name}  branch: {out['branch']}")
        return

    session = session_mod.load_session_soft(sp)
    if session is None:
        out = {
            "active": False,
            "pointer_error": True,
            "repo_root": str(repo_root.resolve()),
            "branch": git_ops.get_current_branch_safe(repo_root),
            "detail": "Active pointer points at a missing or invalid session file.",
        }
        if as_json:
            typer.echo(json.dumps(json_envelope(out, repo_root=repo_root), indent=2))
        else:
            typer.secho(
                "current_session.json points at a missing or unreadable session file. "
                "Run `ignition doctor` or fix/delete the pointer.",
                fg=typer.colors.YELLOW,
                err=True,
            )
        return

    payload = current_cmd_mod.build_current_payload(repo_root, session, cfg)
    if as_json:
        typer.echo(json.dumps(json_envelope(payload, repo_root=repo_root), indent=2))
        return

    ux_mod.section_header("Active session")
    typer.echo(f"Task:     {payload['task']}")
    typer.echo(f"Repo:     {payload['repo_name']}  ({payload['repo_root']})")
    typer.echo(f"Branch:   {payload['branch']}")
    typer.echo(f"Started:  {payload.get('started_at', '')}")
    if payload.get("duration_minutes_so_far") is not None:
        typer.echo(f"Duration: ~{payload['duration_minutes_so_far']} min so far")
    typer.echo(f"Changed:  {payload.get('changed_files_count')} file(s)")
    if payload.get("last_checkpoint_at"):
        typer.echo(f"Last checkpoint: {payload['last_checkpoint_at']}")
    else:
        typer.echo("Last checkpoint: (none)")
    if payload.get("scope_drift_warning"):
        typer.secho(payload["scope_drift_warning"], fg=typer.colors.YELLOW)


@app.command("status")
def cmd_status() -> None:
    """Show current session state and scope drift (warn-only)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    sp = session_mod.read_active_session_file(repo_root, cfg.session_dir)
    if not sp:
        typer.secho("No active session.", fg=typer.colors.YELLOW)
        typer.echo(f"Repo: {repo_root}  branch: {git_ops.get_current_branch_safe(repo_root)}")
        return

    session = session_mod.load_session(sp)
    view = status_mod.build_status_view(repo_root, session, cfg)
    session_mod.merge_session_update(sp, {"last_status_at": utc_now_iso()})

    ux_mod.section_header("Session")
    typer.echo(f"Session task: {view.task}")
    typer.echo(f"Repository:   {view.repo_root} ({view.repo_name})")
    if view.worktree_note:
        typer.echo(f"Worktree:     {view.worktree_note}")
    typer.echo(f"Branch:       {view.branch}")
    typer.echo(f"Changed:      {view.changed_files_count} file(s)")
    typer.echo(f"Untracked:    {view.untracked_count} file(s)")
    sc = session.get("scope") or []
    if sc:
        typer.echo(f"In scope:     {view.in_scope_count}  |  Out of scope: {view.out_scope_count}")
        if view.scope_drift_preview:
            typer.echo("Out of scope (sample):")
            for p in view.scope_drift_preview:
                typer.echo(f"  - {p}")
    typer.echo(f"HEAD:         {view.last_commit_line}")
    if view.last_checkpoint:
        typer.echo(f"Last checkpoint: {view.last_checkpoint.get('at', '')}")
    else:
        typer.echo("Last checkpoint: (none)")
    if view.tests_hint:
        typer.echo(view.tests_hint)
    typer.echo("")
    typer.echo("Recent commits:")
    typer.echo(view.recent_commits_excerpt or "(none)")
    if view.scope_drift_warning:
        typer.secho(view.scope_drift_warning, fg=typer.colors.YELLOW)

    ux_mod.section_header("Guidance")
    b = decisions_mod.build_decision_bundle(
        repo_root,
        cfg,
        session,
        None,
        pointer_stale=_pointer_stale(repo_root, cfg),
    )
    if b.risk_flags:
        typer.echo("")
        typer.echo(phrasing.risk_header(cfg))
        for rf in b.risk_flags:
            typer.secho(f"  • {rf}", fg=typer.colors.YELLOW)
    if b.split_changes_hint and b.split_changes_reason:
        typer.secho(f"Change grouping: {b.split_changes_reason}", fg=typer.colors.YELLOW)


@app.command("stop")
def cmd_stop(
    run_tests: Annotated[
        bool,
        typer.Option("--test/--no-test", help="Run configured test command"),
    ] = True,
    parking: Annotated[
        str | None,
        typer.Option("--parking", help="leave | wip | commit | stash | note"),
    ] = None,
) -> None:
    """End session: summary, classification, receipt, optional Git parking."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    sp = session_mod.read_active_session_file(repo_root, cfg.session_dir)
    if not sp:
        typer.secho("No active session.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    session = session_mod.load_session(sp)

    tr = None
    if run_tests and cfg.auto_checkpoint_test_command:
        typer.echo(f"Running tests: {cfg.auto_checkpoint_test_command}")
        tr = run_test_command(repo_root, cfg.auto_checkpoint_test_command)

    pk = (parking or "").lower().strip() or prompts.prompt_stop_parking()
    task = session.get("task", "task")
    branch = session.get("branch", "branch")

    if pk == "wip":
        try:
            h = git_ops.commit_all(repo_root, f"wip: end session — {task}")
            typer.secho(f"WIP commit: {h}", fg=typer.colors.GREEN)
        except git_ops.GitError as e:
            typer.secho(str(e), fg=typer.colors.YELLOW)
    elif pk == "commit":
        try:
            h = git_ops.commit_all(repo_root, f"feat({branch}): {task}")
            typer.secho(f"Commit: {h}", fg=typer.colors.GREEN)
        except git_ops.GitError as e:
            typer.secho(str(e), fg=typer.colors.YELLOW)
    elif pk == "stash":
        try:
            git_ops.stash_push(repo_root, f"session end: {task}")
            typer.secho("Stashed.", fg=typer.colors.GREEN)
        except git_ops.GitError as e:
            typer.secho(str(e), fg=typer.colors.YELLOW)
    stop_note = ""
    if pk == "note":
        stop_note = typer.prompt("End-of-session note (optional)", default="").strip()

    summ = summary_mod.build_stop_summary(repo_root, session, tr)

    bundle = decisions_mod.build_decision_bundle(
        repo_root,
        cfg,
        session,
        tr,
        pointer_stale=False,
    )

    typer.echo("")
    ux_mod.section_header("Session summary")
    typer.echo(f"Status: {summ.final_status}")
    if summ.scope_drift_warning:
        typer.secho(phrasing.scope_drift_line(cfg), fg=typer.colors.YELLOW)
    typer.echo(summ.suggested_next_action)
    typer.echo(f"Files with local changes (vs last commit): {len(summ.files_changed)}")
    if summ.commits_during_session:
        typer.echo("Commits since session start:")
        for c in summ.commits_during_session:
            typer.echo(f"  {c}")
    typer.echo("")
    ux_mod.section_header("What to do next")
    typer.secho(
        f"{phrasing.primary_rec_label(cfg)}: {bundle.primary_key}",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"  {bundle.primary_reason}")
    if bundle.secondary_keys:
        typer.echo(f"Also consider: {', '.join(bundle.secondary_keys)}")
    for sr in bundle.secondary_reasons:
        typer.echo(f"  • {sr}")
    if bundle.risk_flags:
        typer.echo(f"{phrasing.risk_header(cfg)} " + ", ".join(bundle.risk_flags))
    if bundle.split_changes_hint:
        typer.secho(f"Split changes: {bundle.split_changes_reason or 'yes'}", fg=typer.colors.YELLOW)
    typer.echo(f"Suggested clean commit message: {bundle.suggested_clean_message}")
    typer.echo(f"Suggested WIP message:       {bundle.suggested_wip_message}")
    typer.echo("")
    typer.echo("Parking hints (legacy blurbs, not run automatically):")
    for k, v in summ.parking_recommendations.items():
        typer.echo(f"  [{k}] {v}")

    ended = utc_now_iso()
    scope_list = session.get("scope") or []
    si, so = scope_in_out_counts(repo_root, summ.files_changed, scope_list)
    drift_preview = top_out_of_scope(
        repo_root,
        summ.files_changed,
        scope_list,
        cfg.scope_drift_preview_limit,
    )
    dur_min = parse_iso_duration_minutes(session["started_at"], ended)
    wt_path = session.get("worktree_path") or str(repo_root.resolve())
    wt_note = git_ops.worktree_label(repo_root) if session.get("is_worktree") else ""

    working_tree_clean = git_ops.is_working_tree_clean(repo_root)
    stop_note_tags = notes_tags.parse_note_tags(stop_note)
    tag_agg = notes_tags.aggregate_session_notes(session.get("checkpoints") or [], stop_note, stop_note_tags)
    carryforward_mod.merge_amended_into_tag_agg(session, tag_agg)
    readiness = ready_mod.assess_readiness(
        repo_root,
        cfg,
        session,
        test_result_dict=summ.test_result,
        final_status=summ.final_status,
        files_changed=summ.files_changed,
        scope_out_count=so,
        bundle=bundle,
        working_tree_clean=working_tree_clean,
    )
    br = session.get("branch") or ""
    hygiene_hints = hygiene_mod.branch_hygiene_hints(
        repo_root,
        cfg.session_dir,
        branch=br,
        default_branch=cfg.default_branch,
        session_data=session,
    )
    sess_on_branch = hygiene_mod.sessions_on_branch_for_receipt(repo_root, cfg.session_dir, br)

    handoff_one_liner = (
        f"{session.get('repo_name', 'repo')} · {br} · {session.get('task', '')} — "
        f"{readiness.state}: {readiness.summary_line[:120]}"
    )

    cf_block = carryforward_mod.build_carryforward_block(
        tag_agg=tag_agg,
        stop_note=stop_note,
        handoff_summary=handoff_one_liner,
        suggested_next_action=summ.suggested_next_action,
        recommendation_primary=bundle.primary_key,
        session_carryforward_summary=session.get("carryforward_summary"),
    )

    meta = {
        "session_id": session["session_id"],
        "repo_name": session["repo_name"],
        "repo_root": session["repo_root"],
        "branch": session["branch"],
        "task": session["task"],
        "scope": scope_list,
        "definition_of_done": session.get("definition_of_done", ""),
        "started_at": session["started_at"],
        "ended_at": ended,
        "worktree_path": wt_path,
        "worktree_note": wt_note,
        "repo_default_branch": session.get("repo_default_branch"),
    }

    sc_merge = dict(bundle.scorecard)
    if dur_min is not None:
        sc_merge["duration_minutes"] = dur_min

    payload = {
        "session": meta,
        "files_changed": summ.files_changed,
        "files_changed_count": len(summ.files_changed),
        "diff_stat_session": summ.diff_stat_session,
        "commits_during_session": summ.commits_during_session,
        "commits_detailed": summ.commits_detailed,
        "test_result": summ.test_result,
        "final_status": summ.final_status,
        "scope_drift_warning": summ.scope_drift_warning,
        "scope_in_count": si,
        "scope_out_count": so,
        "scope_drift_preview": drift_preview,
        "suggested_next_action": summ.suggested_next_action,
        "cleanup_suggestions": summ.cleanup_suggestions,
        "parking_recommendations": summ.parking_recommendations,
        "checkpoints": session.get("checkpoints", []),
        "file_stats": summ.file_stats,
        "duration_minutes": dur_min,
        "tests_run": summ.test_result is not None and not (summ.test_result or {}).get("skipped"),
        "tests_passed": (
            None
            if not summ.test_result or summ.test_result.get("skipped")
            else summ.test_result.get("exit_code") == 0
        ),
        "worktree_detected": bool(session.get("is_worktree")),
        "decisions_v3": decisions_mod.bundle_to_dict(bundle),
        "session_scorecard": sc_merge,
        "top_level_dirs_touched": sorted(decisions_mod.top_level_dirs(summ.files_changed)),
        "checkpoints_count": len(session.get("checkpoints") or []),
        "wip_commit_count": (
            sum(1 for c in (session.get("checkpoints") or []) if c.get("wip_commit_hash"))
            + wip_like_commit_count(summ.commits_detailed, summ.commits_during_session)
        ),
        "final_action_taken": pk,
        "recommendation_primary": bundle.primary_key,
        "recommendation_secondary": bundle.secondary_keys[0] if bundle.secondary_keys else None,
        "recommendation_reasons": [bundle.primary_reason, *bundle.secondary_reasons],
        "clean_commit_suggestion": bundle.suggested_clean_message,
        "wip_commit_suggestion": bundle.suggested_wip_message,
        "risk_flags": list(bundle.risk_flags),
        "stop_note": stop_note,
        "stop_note_tags": stop_note_tags,
        "open_questions": tag_agg["open_questions"],
        "followups": tag_agg["followups"],
        "risks_noted": tag_agg["risks_noted"],
        "todos_noted": tag_agg["todos_noted"],
        "readiness_state": readiness.state,
        "readiness_reasons": readiness.reasons,
        "readiness_summary": readiness.summary_line,
        "handoff_summary": handoff_one_liner,
        "branch_hygiene_hints": hygiene_hints,
        "sessions_on_current_branch_count": sess_on_branch,
        **cf_block,
    }

    md_path = Path(session.get("receipt_md") or "")
    json_path = Path(session.get("receipt_json") or "")
    if not md_path.name:
        md_path = receipt_dir(repo_root, cfg.receipt_dir) / f"{session['session_id']}.md"
    if not json_path.name:
        json_path = receipt_dir(repo_root, cfg.receipt_dir) / f"{session['session_id']}.json"

    tpl: Path | None = None
    if cfg.receipt_markdown_template:
        tpl = Path(cfg.receipt_markdown_template)
        if not tpl.is_absolute():
            tpl = repo_root / tpl

    rstyle = cfg.receipt_template if cfg.receipt_template in ("default", "compact", "audit") else "default"

    receipts_mod.write_json_receipt(json_path, payload)
    receipts_mod.write_markdown_receipt(md_path, payload, template_path=tpl, style=rstyle)

    link = dict(session.get("linkage") or {})
    link["session_id"] = session["session_id"]
    link["parent_session_id"] = session.get("resumed_from_session_id")
    link["stop_receipt_path"] = str(json_path.resolve())

    session_mod.mark_stopped(
        sp,
        {
            "ended_at": ended,
            "stopped_at": ended,
            "receipt_json": str(json_path),
            "receipt_md": str(md_path),
            "final_status": summ.final_status,
            "suggested_next_action": summ.suggested_next_action,
            "final_action_taken": pk,
            "linkage": link,
            **cf_block,
        },
    )
    session_mod.clear_active_pointer(repo_root, cfg.session_dir)

    typer.echo("")
    typer.secho(f"Receipt (Markdown): {md_path}", fg=typer.colors.GREEN)
    typer.echo(f"Receipt (JSON):     {json_path}")
    if cf_block.get("carryforward_summary"):
        typer.echo("")
        typer.secho("Carry-forward (for your next session):", fg=typer.colors.BLUE)
        typer.echo(cf_block["carryforward_summary"][:400])
    if summ.cleanup_suggestions:
        typer.echo("")
        typer.echo("Suggested commands (review before running):")
        for line in summ.cleanup_suggestions:
            typer.echo(f"  {line}")


@app.command("resume")
def cmd_resume(
    session_id: Annotated[str | None, typer.Option("--session-id", help="Resume a specific session")] = None,
    latest: Annotated[bool, typer.Option("--latest/--no-latest", help="Pick latest vs oldest unfinished")] = True,
    force: Annotated[bool, typer.Option("--force", help="Override stale active session pointer")] = False,
) -> None:
    """Rebind the latest unfinished session (or a specific id) as the active session."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    if session_mod.pointer_repo_mismatch(repo_root, cfg.session_dir) and not force:
        typer.secho(
            "current_session.json references a different repo_root. Fix the pointer or use --force.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    active = session_mod.read_active_session_file(repo_root, cfg.session_dir)
    path, data = resume_mod.find_resume_target(
        repo_root,
        cfg.session_dir,
        session_id=session_id,
        latest=latest,
    )
    if not path or not data:
        typer.secho(
            "No unfinished session found for this repo. Start one with `ignition start` or check session files.",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)

    if active and active.resolve() != path.resolve():
        active_data = session_mod.load_session_soft(active)
        if active_data is not None and session_mod.is_session_unfinished(active_data) and not force:
            typer.secho(
                f"Another active session exists: {active.name}. Use --force to switch to {data['session_id']}.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(1)

    if active and active.resolve() == path.resolve():
        typer.echo(f"Already on active session {data['session_id']}.")
    else:
        res = resume_mod.apply_resume(repo_root, cfg.session_dir, path, data)
        data = res.data
        typer.secho(f"Resumed session {data['session_id']}", fg=typer.colors.GREEN)
        if res.branch_warning:
            typer.secho(res.branch_warning, fg=typer.colors.YELLOW)
        if res.head_warning:
            typer.secho(res.head_warning, fg=typer.colors.YELLOW)

    changed = git_ops.changed_files(repo_root)
    typer.echo(f"Task:        {data.get('task', '')}")
    typer.echo(f"Branch:      {data.get('branch', '')} (git: {git_ops.get_current_branch(repo_root)})")
    typer.echo(f"Scope:       {', '.join(data.get('scope') or []) or '(none)'}")
    cps = data.get("checkpoints") or []
    if cps:
        typer.echo(f"Last checkpoint: {cps[-1].get('at', '')}")
    else:
        typer.echo("Last checkpoint: (none)")
    typer.echo(f"Changed files: {len(changed)}")
    np = carryforward_mod.build_next_payload(repo_root, cfg, branch=data.get("branch"))
    if np.get("prior_session_id"):
        ux_mod.section_header("Last stop on this branch")
        typer.echo(carryforward_mod.format_next_human(np, plain=cfg.plain_language))


@app.command("list")
def cmd_list(
    all_repos: Annotated[bool, typer.Option("--all", help="Include session files from other repo_roots")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
    limit: Annotated[int, typer.Option("--limit", help="Max rows", min=1)] = 20,
) -> None:
    """List recent sessions stored under ignition_data/sessions."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    rows = listing_mod.list_sessions(repo_root, cfg.session_dir, limit=limit, all_repos=all_repos)
    if as_json:
        typer.echo(json.dumps(json_envelope({"sessions": rows}, repo_root=repo_root), indent=2))
        return
    if not rows:
        typer.echo("No sessions found.")
        return
    for r in rows:
        dur = r.get("duration_minutes")
        ds = f"{dur}m" if dur is not None else "—"
        typer.echo(
            f"{r['session_id']}\t{r['status']}\t{r['branch']}\t{ds}\t{r['task'][:60]}"
        )


@app.command("recommend")
def cmd_recommend(
    run_tests: Annotated[
        bool,
        typer.Option("--test/--no-test", help="Run configured test command first"),
    ] = False,
    json_only: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON only")] = False,
) -> None:
    """Rule-based recommendations for what to do next (no Git mutations)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    sp = session_mod.read_active_session_file(repo_root, cfg.session_dir)
    session = session_mod.load_session(sp) if sp else None

    tr = None
    if run_tests and cfg.auto_checkpoint_test_command:
        typer.echo(f"Running tests: {cfg.auto_checkpoint_test_command}")
        tr = run_test_command(repo_root, cfg.auto_checkpoint_test_command)

    bundle = decisions_mod.build_decision_bundle(
        repo_root,
        cfg,
        session,
        tr,
        pointer_stale=_pointer_stale(repo_root, cfg),
    )
    rdir = receipt_dir(repo_root, cfg.receipt_dir)
    rdir.mkdir(parents=True, exist_ok=True)
    safe_ts = utc_now_iso().replace(":", "").replace("+00:00", "Z")[:20]
    path = rdir / f"recommend-{safe_ts}.json"

    out = {
        "session_id": session.get("session_id") if session else None,
        **decisions_mod.bundle_to_dict(bundle),
    }
    receipts_mod.write_json_receipt(path, out)

    if sp:
        data = session_mod.load_session(sp)
        ev = list(data.get("recommend_events") or [])
        ev.append({"at": utc_now_iso(), "primary_recommendation": bundle.primary_key})
        link = dict(data.get("linkage") or {})
        linkage_mod.append_path_list(link, "recommend_receipt_paths", path)
        session_mod.merge_session_update(
            sp,
            {"recommend_events": ev, "last_recommend_at": utc_now_iso(), "linkage": link},
        )

    if json_only:
        typer.echo(json.dumps(json_envelope(out, repo_root=repo_root), indent=2))
        typer.echo(str(path), err=True)
        return

    ux_mod.section_header("Recommend")
    typer.echo(f"Wrote {path}")
    typer.secho(f"{phrasing.primary_rec_label(cfg)}: {bundle.primary_key}", fg=typer.colors.GREEN)
    typer.echo(bundle.primary_reason)
    if bundle.secondary_keys:
        typer.echo(f"Also: {', '.join(bundle.secondary_keys)}")
    if bundle.risk_flags:
        typer.echo(f"{phrasing.risk_header(cfg)} " + ", ".join(bundle.risk_flags))
    typer.echo(f"Clean commit message: {bundle.suggested_clean_message}")
    typer.echo(f"WIP message:            {bundle.suggested_wip_message}")
    if bundle.git_commands:
        typer.echo("Suggested commands (manual):")
        for c in bundle.git_commands:
            typer.echo(f"  {c}")


@app.command("snapshot")
def cmd_snapshot(
    run_tests: Annotated[
        bool,
        typer.Option("--test/--no-test", help="Include configured test run in snapshot"),
    ] = False,
) -> None:
    """Record a point-in-time snapshot on the active session (no commit/stash)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    sp = session_mod.read_active_session_file(repo_root, cfg.session_dir)
    if not sp:
        typer.secho("No active session.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    session = session_mod.load_session(sp)
    tr_dict = None
    if run_tests and cfg.auto_checkpoint_test_command:
        tr = run_test_command(repo_root, cfg.auto_checkpoint_test_command)
        tr_dict = summary_mod.test_result_to_dict(tr)

    snap = {
        "at": utc_now_iso(),
        "head": git_ops.head_hash(repo_root),
        "branch": git_ops.get_current_branch(repo_root),
        "changed_files": git_ops.changed_files(repo_root),
        "diff_stat": git_ops.diff_stat(repo_root),
        "recent_commits": git_ops.recent_commits(repo_root, n=max(5, cfg.max_recent_commits)),
        "test_result": tr_dict,
    }
    session_mod.append_snapshot(sp, snap)

    rdir = receipt_dir(repo_root, cfg.receipt_dir)
    rdir.mkdir(parents=True, exist_ok=True)
    safe_ts = snap["at"].replace(":", "").replace("+00:00", "Z")[:20]
    out_path = rdir / f"snapshot-{session['session_id']}-{safe_ts}.json"
    receipts_mod.write_json_receipt(out_path, {"snapshot": snap, "session_id": session["session_id"]})
    data_snap = session_mod.load_session(sp)
    link = dict(data_snap.get("linkage") or {})
    linkage_mod.append_path_list(link, "snapshot_receipt_paths", out_path)
    session_mod.merge_session_update(sp, {"last_snapshot_at": utc_now_iso(), "linkage": link})
    typer.secho(f"Snapshot recorded on session and written to {out_path}", fg=typer.colors.GREEN)


@app.command("review")
def cmd_review(
    days: Annotated[int, typer.Option("--days", "-d", help="Look back this many days")] = 7,
    sessions: Annotated[int | None, typer.Option("--sessions", help="Cap how many sessions")] = None,
    all_repos: Annotated[bool, typer.Option("--all", help="Include receipts from other repo_root values")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
) -> None:
    """Summarize recent sessions: counts, averages, patterns (rule-based)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    payload = review_mod.build_review(
        repo_root,
        cfg.session_dir,
        cfg.receipt_dir,
        days=days,
        sessions_limit=sessions,
        all_repos=all_repos,
    )
    payload["generated_at"] = utc_now_iso()
    path = review_mod.write_review_receipt(repo_root, cfg.receipt_dir, payload)

    if as_json:
        typer.echo(json.dumps(json_envelope(payload, repo_root=repo_root), indent=2))
        typer.echo(str(path), err=True)
        return

    ux_mod.section_header("Review")
    typer.echo(f"Wrote {path}")
    if cfg.plain_language:
        typer.echo(f"Sessions counted: {payload.get('session_count', 0)} (last {days} days)")
    else:
        typer.echo(f"Sessions in window: {payload.get('session_count', 0)} (last {days} days)")
    if payload.get("session_count", 0) == 0:
        return
    typer.echo(f"Total duration (sum): {payload.get('total_duration_minutes')} min")
    typer.echo(f"Avg files changed: {payload.get('average_files_changed')}")
    typer.echo(f"Tests run / pass / fail: {payload.get('tests_run_count')} / {payload.get('tests_pass_count')} / {payload.get('tests_fail_count')}")
    typer.echo(f"Status mix: {payload.get('status_breakdown')}")
    if cfg.plain_language:
        typer.echo(f"Sessions with out-of-scope edits: {payload.get('sessions_with_scope_drift')}")
    else:
        typer.echo(f"Sessions with scope drift: {payload.get('sessions_with_scope_drift')}")
    for line in payload.get("patterns_noticed") or []:
        typer.echo(f"• {line}")


@app.command("explain-session")
def cmd_explain_session(
    session_id: Annotated[str, typer.Argument(help="Session id (matches JSON stem)")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Plain-language summary of one session."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    raw = explain_mod.load_session_payload(repo_root, session_id, cfg.session_dir, cfg.receipt_dir)
    if not raw:
        typer.secho(f"No session or receipt found for `{session_id}`.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if as_json:
        typer.echo(
            json.dumps(json_envelope(explain_mod.explain_session_json(raw), repo_root=repo_root), indent=2),
        )
        return

    ux_mod.section_header("Explain session")
    text = explain_mod.explain_session_text(raw, plain_language=cfg.plain_language)
    typer.echo(text)


@app.command("trends")
def cmd_trends(
    days: Annotated[int, typer.Option("--days", "-d", help="Look back period")] = 30,
    all_repos: Annotated[bool, typer.Option("--all")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Trend metrics over time (structured numbers, no charts)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    payload = trends_mod.build_trends(
        repo_root,
        cfg.session_dir,
        cfg.receipt_dir,
        days=days,
        all_repos=all_repos,
    )
    payload["generated_at"] = utc_now_iso()
    path = trends_mod.write_trends_receipt(repo_root, cfg.receipt_dir, payload)

    if as_json:
        typer.echo(json.dumps(json_envelope(payload, repo_root=repo_root), indent=2))
        typer.echo(str(path), err=True)
        return

    ux_mod.section_header("Trends")
    typer.echo(f"Wrote {path}")
    typer.echo(f"Period: {days} days, sessions: {payload.get('session_count')}")
    typer.echo(f"Sessions / week: {payload.get('sessions_per_week')}")
    typer.echo(f"Averages: {payload.get('averages')}")
    typer.echo(f"Rates: {payload.get('rates')}")
    for o in payload.get("observations") or []:
        typer.echo(f"• {o}")


@app.command("handoff")
def cmd_handoff(
    session_id: Annotated[str | None, typer.Option("--session-id", help="Specific session")] = None,
    current: Annotated[bool, typer.Option("--current", help="Active session")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Write a concise handoff markdown + JSON (reviewer-friendly)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    if session_id and current:
        typer.secho("Use either --session-id or --current, not both.", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    rec, err = handoff_mod.resolve_handoff_record(
        repo_root,
        cfg.session_dir,
        cfg.receipt_dir,
        session_id=session_id,
        use_current=current,
    )
    if err or not rec:
        typer.secho(err or "Nothing to hand off.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    sid = (rec.get("session") or {}).get("session_id") or rec.get("session_id") or "unknown"
    payload = handoff_mod.build_handoff_payload(
        repo_root,
        cfg.session_dir,
        cfg.receipt_dir,
        rec,
        default_branch=cfg.default_branch,
    )
    md_path, js_path = handoff_mod.write_handoff_artifacts(repo_root, cfg.receipt_dir, sid, payload)

    sp_hand = session_mod.session_file_path(repo_root, cfg.session_dir, sid)
    if sp_hand.is_file():
        sd = session_mod.load_session_soft(sp_hand)
        if sd:
            lk = dict(sd.get("linkage") or {})
            lk["handoff_receipt_path"] = str(js_path.resolve())
            session_mod.merge_session_update(sp_hand, {"linkage": lk})

    if as_json:
        typer.echo(json.dumps(json_envelope(payload, repo_root=repo_root), indent=2))
        typer.echo(str(js_path), err=True)
        return

    ux_mod.section_header("Handoff")
    typer.secho(f"Wrote {md_path}", fg=typer.colors.GREEN)
    typer.echo(str(js_path))
    typer.echo("")
    typer.echo(payload.get("handoff_summary", ""))


@app.command("ready")
def cmd_ready(
    run_tests: Annotated[
        bool,
        typer.Option("--test/--no-test", help="Run configured test command first"),
    ] = True,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Rule-based merge/review readiness hint (not proof)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    sp = session_mod.read_active_session_file(repo_root, cfg.session_dir)
    if not sp:
        typer.secho("No active session.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    session = session_mod.load_session(sp)
    tr = None
    tr_dict: dict | None = None
    if run_tests and cfg.auto_checkpoint_test_command:
        typer.echo(f"Running tests: {cfg.auto_checkpoint_test_command}")
        tr = run_test_command(repo_root, cfg.auto_checkpoint_test_command)
        tr_dict = summary_mod.test_result_to_dict(tr)

    bundle = decisions_mod.build_decision_bundle(
        repo_root,
        cfg,
        session,
        tr,
        pointer_stale=_pointer_stale(repo_root, cfg),
    )
    assessment = ready_mod.assess_live_session(
        repo_root,
        cfg,
        session,
        bundle=bundle,
        test_result_dict=tr_dict,
    )
    br = session.get("branch") or ""
    hints = hygiene_mod.branch_hygiene_hints(
        repo_root,
        cfg.session_dir,
        branch=br,
        default_branch=cfg.default_branch,
        session_data=session,
    )
    out = {
        "readiness_state": assessment.state,
        "readiness_reasons": assessment.reasons,
        "summary_line": assessment.summary_line,
        "branch_hygiene_hints": hints,
        "primary_recommendation": bundle.primary_key,
    }
    if as_json:
        typer.echo(json.dumps(json_envelope(out, repo_root=repo_root), indent=2))
        return

    ux_mod.section_header("Ready?")
    typer.secho(f"State: {assessment.state}", fg=typer.colors.GREEN)
    typer.echo(assessment.summary_line)
    if assessment.reasons:
        for r in assessment.reasons:
            typer.echo(f"  • {r}")
    if hints:
        typer.echo("")
        typer.echo("Branch hygiene:")
        for h in hints:
            typer.echo(f"  • {h}")


@app.command("timeline")
def cmd_timeline(
    session_id: Annotated[str, typer.Argument(help="Session id")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show timestamped session events (start, checkpoints, snapshots, recommends, stop)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    merged = timeline_mod.load_timeline_session(repo_root, cfg.session_dir, cfg.receipt_dir, session_id)
    if not merged:
        typer.secho(f"No session `{session_id}` found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    events = timeline_mod.build_timeline(merged)
    if as_json:
        typer.echo(
            json.dumps(
                json_envelope({"session_id": session_id, "events": events}, repo_root=repo_root),
                indent=2,
            ),
        )
        return

    ux_mod.section_header("Timeline")
    for e in events:
        typer.echo(f"{e.get('at', '')}  [{e.get('type')}]  {e.get('detail', '')}")


@app.command("close-stale")
def cmd_close_stale(
    days: Annotated[int, typer.Option("--days", "-d", help="Sessions started before this window")] = 14,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show candidates only")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
) -> None:
    """Mark very old unfinished sessions as stale (does not delete session files)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    cands = stale_mod.find_stale_sessions(repo_root, cfg.session_dir, older_than_days=days)
    if not cands:
        typer.echo("No stale unfinished sessions found.")
        raise typer.Exit(0)

    ux_mod.section_header("Close stale")
    for c in cands:
        typer.echo(f"  • {c.session_id}  started {c.started_at}")
    if dry_run:
        typer.echo("(dry-run: no changes)")
        raise typer.Exit(0)

    if not yes and not typer.confirm(f"Mark {len(cands)} session(s) as stale_closed?", default=False):
        typer.echo("Aborted.")
        raise typer.Exit(1)

    reason = f"No stop recorded within {days} days; closed as stale by close-stale"
    for c in cands:
        rp = stale_mod.close_stale_session(
            repo_root,
            cfg.session_dir,
            cfg.receipt_dir,
            c.path,
            reason=reason,
        )
        cleared = stale_mod.clear_pointer_if_points_to(repo_root, cfg.session_dir, c.path)
        typer.secho(f"Closed {c.session_id} → receipt {rp.name}" + (" (cleared active pointer)" if cleared else ""), fg=typer.colors.GREEN)


hook_app = typer.Typer(
    help="Print optional shell snippets (never edits your rc files).",
    no_args_is_help=True,
)


@hook_app.command("print")
def cmd_hook_print(
    shell: Annotated[str, typer.Option("--shell", help="bash | zsh | fish")] = "zsh",
) -> None:
    """Print aliases and an optional prompt snippet to copy into ~/.zshrc etc."""
    s = shell.lower().strip()
    if s not in ("bash", "zsh", "fish"):
        typer.secho("Use --shell bash, zsh, or fish.", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    typer.echo(hooks_mod.hook_print_body(s))


app.add_typer(hook_app, name="hook")


@app.command("export")
def cmd_export(
    all_repos: Annotated[bool, typer.Option("--all", help="Include sessions from other repo_root values")] = False,
    days: Annotated[int | None, typer.Option("--days", help="Only sessions started in the last N days")] = None,
    fmt: Annotated[str, typer.Option("--format", help="json | jsonl | markdown-bundle")] = "json",
    compress: Annotated[bool, typer.Option("--compress", help="gzip the export file")] = False,
    output: Annotated[Path | None, typer.Option("-o", "--output", help="Destination file path")] = None,
) -> None:
    """Export sessions and receipts to a portable bundle under ignition_data/exports/."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    if fmt not in ("json", "jsonl", "markdown-bundle"):
        typer.secho("Use --format json, jsonl, or markdown-bundle.", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)

    dest = output
    if dest is None:
        dest = exports_dir(repo_root) / export_import_mod.default_export_filename(fmt, compress)
    dest.parent.mkdir(parents=True, exist_ok=True)

    try:
        out = export_import_mod.export_to_path(
            repo_root,
            cfg.session_dir,
            cfg.receipt_dir,
            dest,
            all_repos=all_repos,
            days=days,
            fmt=fmt,
            compress=compress,
        )
    except ValueError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from e
    typer.secho(f"Export written: {out}", fg=typer.colors.GREEN)


@app.command("import")
def cmd_import(
    path: Annotated[Path, typer.Argument(help="Path to an export file (.json, .jsonl, .zip, or .gz)")],
) -> None:
    """Import sessions/receipts from a bundle produced by `ignition export`."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    if not path.is_file():
        typer.secho(f"Not a file: {path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    cfg = load_config(repo_root)
    res = export_import_mod.import_bundle_path(repo_root, cfg.session_dir, cfg.receipt_dir, path)
    for w in res.warnings:
        typer.secho(w, fg=typer.colors.YELLOW, err=True)
    typer.echo(
        f"Sessions: imported {res.sessions_imported}, skipped {res.sessions_skipped}. "
        f"Receipts: imported {res.receipts_imported}, skipped {res.receipts_skipped}."
    )


@app.command("prune")
def cmd_prune(
    dry_run: Annotated[bool, typer.Option("--dry-run", help="List what would be removed")] = False,
) -> None:
    """Remove disposable artifacts only (.tmp under ignition_data, zero-byte junk under exports)."""
    repo_root = git_ops.find_git_root()
    if repo_root is None:
        typer.secho("Error: not inside a Git repository.", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)

    counts = export_import_mod.run_prune(repo_root, dry_run=dry_run)
    label = "Would remove" if dry_run else "Removed"
    typer.echo(
        f"{label}: {counts['tmp_removed']} .tmp file(s), {counts['empty_removed']} empty file(s) under exports.",
    )


@app.command("doctor")
def cmd_doctor(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable checks")] = False,
) -> None:
    """Validate repo state and IGNITION configuration."""
    repo_root = git_ops.find_git_root()
    checks = doctor_mod.run_doctor(repo_root)
    if as_json:
        payload = {"checks": doctor_mod.checks_to_dict(checks)}
        typer.echo(json.dumps(json_envelope(payload, repo_root=repo_root), indent=2))
        exit_code = 0
        for c in checks:
            if c.level == "fail":
                exit_code = 1
        raise typer.Exit(exit_code)

    exit_code = 0
    for c in checks:
        color = typer.colors.GREEN
        if c.level == "warn":
            color = typer.colors.YELLOW
        elif c.level == "fail":
            color = typer.colors.RED
            exit_code = 1
        typer.secho(f"[{c.level.upper():4}] {c.name}: {c.detail}", fg=color)
        if c.fix:
            typer.echo(f"       → {c.fix}")
    raise typer.Exit(exit_code)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
