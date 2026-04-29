# IGNITION

IGNITION is a **developer session engine**: a thin CLI that frames coding work as bounded sessions with checkpoints and receipts. You turn it on when you start, checkpoint while the work is messy, and stop when you park.

## Why this exists (even though Git / GitHub / Git Town / worktrees exist)

Git records commits. Git Town automates branch workflows. Worktrees give parallel working directories. **None of that defines a session**: a named task, declared scope, checkpoints you chose, and a **receipt** you can audit later.

IGNITION stays in that gap—it is **not** a second source control system, not a hosting client, not an auto-rebase tool. It is a **session wrapper and decision layer** on top of normal Git.

## Core commands

| Command | Role |
|--------|------|
| `ignition start` | Capture task / scope / definition of done, optional feature branch, session + receipt stub. |
| `ignition checkpoint` | Diff snapshot, optional tests, optional WIP commit or stash, append checkpoint (records `HEAD`). |
| `ignition status` | Task, branch, in/out scope counts, drift sample, worktree note, recent commits, **risk flags**, split-change hints. |
| `ignition stop` | Parking choice, **primary + secondary recommendations with reasons**, suggested commit messages, scorecard, receipts, clear active pointer. |

## v2: continuity & hygiene

| Command | Role |
|--------|------|
| `ignition resume` | Rebind an unfinished session (`--session-id`, `--latest` / `--no-latest`, `--force`). |
| `ignition list` | Recent sessions (`--limit`, `--all`, `--json`). |
| `ignition doctor` | Pass/warn/fail checks (repo, pointer, dirs, tests on `PATH`, worktree, identity, untracked volume). |

## v3: land the session well

| Command | Role |
|--------|------|
| `ignition recommend` | **Rule-based** next steps: primary/secondary recommendation keys, reasons, risk flags, suggested clean/WIP commit messages, example `git` lines. Writes `ignition_data/receipts/recommend-*.json`. `--test` runs your test command first; `--json` prints machine-readable output. **Does not mutate Git.** |
| `ignition snapshot` | **Black-box recorder**: append a timestamped snapshot to the active session (changed files, diff stat, `HEAD`, recent commits, optional test run) and write `ignition_data/receipts/snapshot-<session>-*.json`. No commit/stash required. |

At **`ignition stop`**, you get a concrete “what to do next” block (tests failing → fix first; many dirs touched → consider splitting; on default branch with dirt → stash/switch; etc.), plus **session scorecard** metrics on the receipt for audit and self-review—not gamification.

Recommendation keys are deterministic examples such as: `fix_tests_first`, `make_wip_commit`, `stash_and_switch`, `safe_to_commit_cleanly`, `clean_scope_before_commit`, `split_changes_into_multiple_commits`, `review_before_merge`, `keep_working`. **Nothing runs automatically.**

## v4: after the session ends

IGNITION is most obviously useful **while** you are in a session—but the receipts also answer questions once you have moved on: what happened lately, whether endings were messy, where you actually edited, and whether scope drift keeps showing up. This is **not** a replacement for Git discipline; it makes that discipline **visible over time** so you can audit your own habits. There is no scoring, no “coach” persona, and no network or LLM involved.

| Command | Role |
|--------|------|
| `ignition review` | Roll up recent sessions for this repo (default last 7 days): counts, durations, file/test averages, status mix, scope-drift sessions, common recommendations and directories, **deterministic** “patterns noticed” lines. `--days`, `--sessions`, `--all`, `--json`. Writes `ignition_data/receipts/review-*.json`. |
| `ignition explain-session <id>` | One session in plain language: task, branch, duration, what changed, scope/tests, how it ended, what was recommended, what parking you chose. `--json` for structured + dual summaries. |
| `ignition trends` | Numeric trends over a window (default 30 days): sessions per week, averages, rates (clean / dirty / failing tests / scope drift), weekly bucket counts, short observations. `--days`, `--all`, `--json`. Writes `ignition_data/receipts/trends-*.json`. |

**Examples** (after you have a few stopped sessions with receipts):

```bash
ignition review --days 7
ignition explain-session <session-id-from-list-or-receipt>
ignition trends --days 30
```

Session receipts gain normalized fields (files changed, dirs touched, checkpoint counts, WIP-style commit hints, test flags, recommendations, risk flags) so older JSON still loads: missing fields are filled with safe defaults when possible.

Optional **`plain_language = true`** in `ignition.toml` softens terminal wording for `status`, `recommend`, `review`, and `explain-session` where wired—structured JSON output is unchanged.

## v5: low friction (habit-friendly)

The goal is to shrink the gap between “I should start a session” and “I did.” IGNITION still does not run in the background, edit your shell files for you, or lock you into a workflow—it only makes the **happy path shorter** and **active session state obvious**.

| Command | Role |
|--------|------|
| `ignition init` | Create `ignition.toml` (if missing), session/receipt/template dirs, detect default branch, embed a suggested test command when obvious. Prints a one-line hint to run `ignition hook print`. **Never modifies `~/.zshrc`.** |
| `ignition start` | Same as before, with **`--yes` / `-y`** (non-interactive; requires `--task`), **`--print-assumptions`**, and **`--force`** (start despite an active session). On the default branch, infers a feature branch name from the task; scope defaults from `[project].preferred_scope` or from **current changed files**; skips interactive prompts when `--yes` is set (dirty tree defaults to *keep*). |
| `ignition current` | One tight block: active or not, task, branch, duration so far, last checkpoint, changed file count, drift warning. `--json` for scripts and prompt snippets. |
| `ignition close-stale` | Mark **old unfinished** sessions as `stale_closed` (no deletion), write `stale-closed-*.json` receipt, clear `current_session.json` if it pointed at a closed session. `--days`, `--dry-run`, `--yes`. |
| `ignition hook print` | Print optional **bash / zsh / fish** snippets: short aliases (`igs`, `igc`, …) and an optional prompt helper that calls `ignition current --json`. Copy into your rc file yourself. |

**Duplicate-session guardrails:** starting a new session while another is active on the **same branch** is blocked (use `resume` / `stop` or `--force`). If the active session is for a **different branch**, you get a strong warning and must confirm (or use `--force`). If `current_session.json` points at **another clone’s root**, start is blocked unless `--force`.

**Session “heartbeats”** (no daemon): `last_status_at`, `last_recommend_at`, and `last_snapshot_at` on the session file update when you run `status`, `recommend`, and `snapshot`.

### How to make IGNITION part of your normal routine

1. **Once per repo:** `ignition init` (or copy an `ignition.toml` from another project).
2. **Optional:** `ignition hook print --shell zsh` → paste the aliases into `~/.zshrc` so `igs` / `igcur` are muscle memory.
3. **When you sit down to work:** `ignition start --task "short label" --yes` (under ten seconds if the tree is clean or you accept keeping dirty changes).
4. **Any time:** `ignition current` to see whether a session is active—faster than reading `status` when you only need the headline.
5. **Occasionally:** `ignition close-stale --dry-run` to list abandoned sessions, then run without `--dry-run` to mark them closed without deleting history.

### Quickstart with aliases (after `hook print`)

```bash
igs() { ignition start "$@"; }   # or use the printed aliases: igs, igc, igst, igx, igcur
ignition start --task "fix login" --yes
ignition current
```

## v6: handoff, review, and merge prep (still local)

IGNITION does **not** talk to GitHub/GitLab, open PRs, or rewrite history. It helps you bridge **session intent → session result → merge readiness** with short, shareable text and rule-based hints—useful for **you**, **reviewers**, and **teammates** reading a handoff doc or ticket.

| Command | Role |
|--------|------|
| `ignition handoff` | Writes `ignition_data/receipts/handoff-<session_id>.md` and `.json`: repo/branch/task/scope, what changed, tests, drift/risks, recommendations, suggested PR title line, parsed **todo:/risk:/question:/followup:** notes, readiness snapshot, branch hygiene hints. `--current`, `--session-id`, `--json`. |
| `ignition ready` | Heuristic state only: `not_ready`, `review_ready`, or `merge_ready_candidate`—with a plain summary (not proof). Uses tree cleanliness, tests (optional `--test`), scope drift, split-change hints, branch vs default. **`--json`**. |
| `ignition timeline <session-id>` | Timestamped **start → checkpoints → snapshots → recommend → stop** for one session. **`--json`**. |

**Structured checkpoint/stop notes (optional):** lines like `todo: …`, `risk: …`, `question: …`, `followup: …` are parsed into checkpoint metadata and receipts (free text still allowed).

**Branch hygiene (hints only):** e.g. many sessions on the same branch without a `clean_complete` stop—surfaced in handoff and `ready` where relevant.

**Receipt fields (v6, backward compatible):** `handoff_summary`, `open_questions`, `followups`, `risks_noted`, `readiness_state`, `readiness_reasons`, `sessions_on_current_branch_count`, `branch_hygiene_hints`, plus `stop_note` / tag buckets when applicable.

## v7: routine + project memory (local)

`ignition start` is still the full explicit entry. **`ignition begin`** is the daily front door: it blocks starting a *second* unfinished session on the same branch (suggests `resume` first), prints a short **“where you left off”** line from the last **stopped** session, runs the same path as `start` with **assumptions printed**, and copies a small **inherited carry-forward** block onto the new session file when relevant.

| Command | Role |
|--------|------|
| `ignition begin` | Like `start`, but suggests `resume` when an unfinished session already exists on the current branch (`--force` to start anyway). Prints prior context, then starts with `--print-assumptions` behavior. |
| `ignition next` | Very short “what was I doing?” from the last **stopped** session on this branch: task, ending, todos/risks/questions, suggested next, hygiene hint. `--json`. |
| `ignition amend-context` | Edit active session (`--session-id` optional): `--task`, `--scope`, `--done`, `--summary`, plus `--todo` / `--risk` / `--question` / `--followup` (append lines). |
| `ignition checklist` | Prints `[project].merge_checklist` and `review_command` if set; soft message if empty. |

**Carry-forward on stop:** session + receipt store `carryforward_*` fields (todos, risks, questions, followups, summary, suggested next) derived from tags, stop note, and recommendations. **`resume`** prints a short “last stop on this branch” block after rebinding.

**Config (`[project]`):** optional `merge_checklist` (list of strings), `review_command`, `common_paths`, `notes_style`, `preferred_branch_prefix` (same role as `feature_prefix`).

### Example: review-oriented flow

```text
ignition start --task "API hardening" --yes
ignition checkpoint --action note --note "todo: add test
risk: auth edge case"
ignition recommend
ignition stop --parking note
ignition handoff --current          # or --session-id <id>
ignition ready
ignition timeline <session-id>
```

### Habit loop (v7)

```text
ignition begin --task "today" --yes
ignition checkpoint ...
ignition recommend
ignition stop
ignition next          # before the next sit-down
ignition resume        # or begin again
ignition checklist
```

## v8: durability and portability (still local)

IGNITION is meant to be **safe to rely on for months**: session and receipt JSON carry a `schema_version`, older shapes are **normalized in memory** when loaded (files are not rewritten automatically), and writes use **atomic rename** to avoid torn JSON after a crash.

| Command | Role |
|--------|------|
| `ignition export` | Bundle sessions + receipt payloads to `ignition_data/exports/` (default JSON). `--all`, `--days N`, `--format` (`json`, `jsonl`, `markdown-bundle`), `--compress`, `-o path`. |
| `ignition import <file>` | Merge an export into this clone. Matches on `session_id`; **skips** when local data looks newer (by activity timestamps). Prints imported/skipped counts. |
| `ignition prune` | Deletes only disposable junk: `*.tmp` under `ignition_data/`, empty stub files under `exports/`. Does **not** remove sessions or receipts by default. |

**JSON outputs (`--json`):** Commands such as `current`, `list`, `doctor`, `recommend`, `review`, `explain-session`, `trends`, `handoff`, `ready`, `timeline`, and `next` emit a stable top layer: `tool_version`, `schema_version`, `generated_at`, and usually `repo_root`, merged with command-specific fields (`list` wraps rows in `sessions`).

**Linkage:** Each session record may include a `linkage` object (`stop_receipt_path`, `handoff_receipt_path`, `recommend_receipt_paths`, `snapshot_receipt_paths`, `parent_session_id`, etc.) so tools can traverse receipts without guessing paths.

**Recovery:** If `current_session.json` or a session file is corrupt, commands **fail softly** where possible (`doctor` warns; `list` skips bad files; `current` reports a pointer error). Use `ignition export` periodically for backup before risky edits.

## v9: machine-readable surface (MCP server)

IGNITION ships an optional **MCP server** (Model Context Protocol) so agent clients — Claude in Cowork, IDE extensions, etc. — can read session state and start / resume sessions over a structured protocol. Same on-disk format as the CLI; no parallel state.

| Tool | Role |
|------|------|
| `ignition_current` | Active-session snapshot, or `{"active": false}` if none. |
| `ignition_next` | Carry-forward block from the last stopped session on this branch. |
| `ignition_status` | Full status view: scope, drift, last checkpoint, recent commits. |
| `ignition_init` | Create `ignition.toml` and data dirs. Refuses to clobber unless `force=true`. |
| `ignition_begin` | Start a session. Guards against duplicate-on-same-branch and pointer-from-another-clone (overridable with `force=true`). |
| `ignition_resume` | Rebind the active pointer to an unfinished session. |

Tool names retain the `ignition_` prefix on purpose so they stay unambiguous in multi-MCP agent transcripts (where bare `current` or `begin` would collide with other servers).

**Install:**

```bash
pip install -e ".[mcp]"
ignition-mcp --help
```

**Cowork `mcp.json` snippet:**

```json
{
  "mcpServers": {
    "ignition": {
      "command": "/abs/path/to/IGNITION/.venv/bin/ignition-mcp",
      "env": { "IGNITION_DEFAULT_PROJECT": "${workspaceFolder}" }
    }
  }
}
```

`IGNITION_DEFAULT_PROJECT` is the fallback for any tool called without an explicit `project_path` argument (mirrors KeySmith's `KEYSMITH_DEFAULT_PROJECT`).

**Errors are data, not exceptions.** Every tool wraps its body in try/except and returns `{"error": "...", "code": "..."}` on failure (matches KeySmith's pattern) so agent clients can react instead of seeing tool-error termination.

**Round-trips with the CLI.** Sessions started via `ignition_begin` are bit-for-bit identical on disk to those started via `ignition start`. You can mix and match — start via the agent, checkpoint via the CLI, stop via either.

## Messy-but-professional workflow

1. `ignition start --task "real task" --scope src/,tests/`
2. Work; use `ignition checkpoint` when you need a recovery point (optionally tag lines with `todo:` / `risk:` / …).
3. `ignition status` — see drift and risk flags before you commit.
4. `ignition snapshot` before a risky experiment (optional).
5. `ignition recommend` when unsure what Git move comes next.
6. `ignition stop --parking note` (or leave/WIP/stash/commit as appropriate).
7. `ignition handoff` / `ignition ready` when you need a shareable summary or a merge-readiness sniff test.

This reduces **bad merges**, **noisy history**, and **pretending WIP is done**—without taking the keyboard away from you.

## Git worktrees

IGNITION detects linked worktrees and records paths in metadata. It does **not** manage worktrees; it reports them so sessions stay honest about *where* work happened.

## Configuration

Optional `ignition.toml`:

```toml
default_branch = "main"
default_feature_branch_prefix = "feature/"
auto_checkpoint_test_command = "pytest -q"
auto_status_test_command = "pytest -q"
session_dir = "ignition_data/sessions"
receipt_dir = "ignition_data/receipts"
receipt_markdown_template = "ignition_data/templates/receipt_append.md"  # optional; {body} placeholder
receipt_template = "default"   # default | compact | audit
recommendation_mode = "balanced"  # conservative | balanced
long_session_minutes = 180
many_commits_threshold = 8
large_untracked_threshold = 15
split_change_directory_threshold = 3
warn_on_scope_drift = true
max_files_before_warning = 8
max_recent_commits = 5
scope_drift_preview_limit = 5
untracked_warning_threshold = 10
plain_language = false   # true: softer phrasing in the terminal for some commands

# Optional per-project defaults (override / augment top-level for this repo)
# [project]
# preferred_scope = ["src/", "tests/"]
# test_command = "pytest -q"
# feature_prefix = "feature/"
# receipt_template = "default"
# recommendation_mode = "balanced"
# plain_language = false
# merge_checklist = ["tests pass", "handoff if incomplete"]
# review_command = "pytest -q"
# common_paths = ["src/", "tests/"]
# notes_style = "tags"   # freeform; informational only
# preferred_branch_prefix = "feature/"
```

## Artifacts

- **Sessions:** JSON with checkpoints (including optional `note_tags`), snapshots, `recommend_events`, optional resume metadata.
- **Receipts:** JSON + Markdown with scorecard, `decisions_v3`, risk flags, suggested messages, readiness/heuristic fields, and commands **you** run manually.
- **Handoffs:** `handoff-<session_id>.md` / `.json` for reviewers and tickets (all local files).

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"            # CLI only
# or, with the MCP server:
pip install -e ".[dev,mcp]"
ignition --help
ignition-mcp --help                 # available with the [mcp] extra
```

## Engineering discipline

IGNITION helps answer: what you are working on, what changed, what is safe, what still needs cleanup, and **what to do next**—without replacing Git or hiding behind magic.
