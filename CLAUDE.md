# file-sorter

A safety-first CLI for organizing cluttered directories (primarily `~/Downloads`)
into category folders, built with `typer`, `pydantic`, and `rich`.

## Setup

```bash
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Running

```bash
# Preview only — the default. Nothing is moved.
.venv\Scripts\python.exe -m sorter.cli organize C:\Users\me\Downloads

# Actually move files.
.venv\Scripts\python.exe -m sorter.cli organize C:\Users\me\Downloads --execute

# Reverse the most recent run.
.venv\Scripts\python.exe -m sorter.cli undo --target C:\Users\me\Downloads --execute

# List past runs, generate a custom config.
.venv\Scripts\python.exe -m sorter.cli list-runs --target C:\Users\me\Downloads
.venv\Scripts\python.exe -m sorter.cli init-config my_config.yaml
```

Once installed (`pip install -e .`), the `file-sorter` console script wraps the
same commands: `file-sorter organize ...`.

## Testing

```bash
.venv\Scripts\python.exe -m pytest
```

89 tests cover config validation, rule/category resolution, scanning, move
planning + collision handling, target containment on both the move and undo
paths, the undo ledger and its crash-safety journal, and the CLI end-to-end
(via `typer.testing.CliRunner`). One symlink test skips where the account
lacks `SeCreateSymbolicLinkPrivilege`, which is the normal Windows case.

## Architecture

| Module | Responsibility |
|---|---|
| [sorter/paths.py](sorter/paths.py) | The one definition of "inside the target directory", used by `scanner`, `mover` and `history` alike. Imports nothing from `sorter`, so all three can reach it without a cycle. |
| [sorter/config.py](sorter/config.py) | Pydantic schema for `config.yaml`; validates and normalizes user config (fails fast on bad input). |
| [sorter/rules.py](sorter/rules.py) | `RuleEngine.categorize()` — extension lookup first, MIME-type sniffing as fallback, then `fallback_category`. Also resolves date-based subfolders. |
| [sorter/scanner.py](sorter/scanner.py) | Walks the target directory (non-recursive by default), filtering out hidden files, junk filenames, and ignored extensions (`.crdownload`, `.part`, `.tmp`, etc). |
| [sorter/mover.py](sorter/mover.py) | Turns scanned files + categorization into a `MoveOperation` plan, then executes it. Collision handling: identical content (SHA-256) is skipped as a duplicate; differing content is auto-renamed (`file (1).pdf`). Dry-run and execute share the same planning code path. Rejects any destination that escapes the target — see the containment note below. |
| [sorter/history.py](sorter/history.py) | Writes a JSON transaction ledger per run to `<target>/.sorter_history/`, and reverses a run (`undo_run`) by moving files back to their recorded source path. Also owns the write-ahead journal that keeps an interrupted run undoable. |
| [sorter/cli.py](sorter/cli.py) | Typer app wiring: `organize`, `undo`, `list-runs`, `init-config`. Renders `rich` tables for every preview/result. |

## Design decisions worth knowing

- **Dry-run is the default everywhere.** Both `organize` and `undo` require
  `--execute`/`-f` to touch the filesystem. This was an explicit requirement,
  not an oversight — don't "simplify" it away.
- **Nothing moves to a path outside the target — checked at every point of
  mutation, in two layers.** `build_plan` refuses a category or rendered date
  subfolder that is absolute, UNC, a device path (`\\?\`, `\\.\`),
  root-relative, drive-relative, or contains `..`, so bad config fails once
  with a clear message. `execute_plan` and `undo_run` then re-check the
  *resolved* src and dst of every operation against the resolved target and
  record `rejected_outside_target` instead of acting. Both layers are needed:
  the lexical one cannot see a category directory that is a junction pointing
  outside the target, and the resolved one alone would report N identical
  rejections instead of naming the config key at fault.

  The joining is what makes this necessary and it is silent — on Windows
  `Path("C:/target") / "C:/Windows/System32"` evaluates to
  `C:/Windows/System32`, discarding the base entirely.

  Two rules for anyone extending this. **Reject, never clamp**: a destination
  outside the target means the config or the plan is wrong, and quietly
  rewriting it to something inside moves the file somewhere nobody asked for
  and hides the cause. And **never write the check as a `startswith` string
  comparison** — `PurePath.__eq__` is case-insensitive on Windows and
  `resolve()` expands 8.3 short names (`PROGRA~1`), so the path-object form in
  `sorter/paths.py` catches two bypasses a string test does not. `target` is
  a required argument to `execute_plan` for the same reason: a check that can
  be skipped by omitting an argument is not a check.
- **Non-recursive scanning by default.** Once files land in `Images/`,
  `Documents/`, etc., a re-run must not reach into those folders and reshuffle
  already-sorted files. `--recursive` opts back in for edge cases.
- **The undo ledger lives inside the target directory** (`<target>/.sorter_history/`),
  not in a global app-data location, so it travels with the directory and is
  easy to find/inspect. It's excluded from scanning via `ignore.filenames`.
- **Collision resolution is two-tiered**: hash first (skip true duplicates
  without touching them), rename second (never silently overwrite). This
  satisfies both strategies mentioned in the original spec rather than
  picking one.
- **MIME-type fallback only fires for extensions absent from config**, and
  only maps to a category that's actually defined in the loaded config (so a
  minimal custom config with just one category doesn't get surprise buckets
  invented for it).
- Individual file errors (permissions, locked files) are caught per-file
  during `execute_plan`/`undo_run` and recorded with `status="error"` — one
  bad file never aborts the whole run.
- **The undo record is written ahead of the move, not after it.**
  `start_journal()` opens a `<run_id>.jsonl` write-ahead log before the first
  move and `execute_plan`'s `on_intent` hook appends each record (fsynced)
  before the corresponding `shutil.move`. A completed run writes the real
  `<run_id>.json` ledger and deletes the journal; an interrupted one leaves the
  journal, which `load_ledger`/`list_runs` fall back to so `undo` still works.
  The asymmetry is deliberate: a crash may leave a record for a move that never
  happened (`undo_run` reports `skipped_missing`, harmless), but never a move
  with no record.

## Extending

- New categories/extensions: edit `config.yaml` (see `sorter/default_config.yaml`
  for the schema) — no code changes needed.
- New MIME-type fallback rules: `_MIME_MAJOR_TO_CATEGORY` / `_MIME_EXACT_TO_CATEGORY`
  in [sorter/rules.py](sorter/rules.py).

## Model routing

Sonnet executes, Opus escalates, Fable only on Travis's explicit say-so. This repo's subagents
live in `.claude/agents/`; the doctrine they point to is `90_Meta/Model Routing.md` in the dev
mono-vault containing this repo — personal workflow config, not part of this project.
