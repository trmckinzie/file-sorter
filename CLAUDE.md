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

52 tests cover config validation, rule/category resolution, scanning, move
planning + collision handling, the undo ledger, and the CLI end-to-end
(via `typer.testing.CliRunner`).

## Architecture

| Module | Responsibility |
|---|---|
| [sorter/config.py](sorter/config.py) | Pydantic schema for `config.yaml`; validates and normalizes user config (fails fast on bad input). |
| [sorter/rules.py](sorter/rules.py) | `RuleEngine.categorize()` — extension lookup first, MIME-type sniffing as fallback, then `fallback_category`. Also resolves date-based subfolders. |
| [sorter/scanner.py](sorter/scanner.py) | Walks the target directory (non-recursive by default), filtering out hidden files, junk filenames, and ignored extensions (`.crdownload`, `.part`, `.tmp`, etc). |
| [sorter/mover.py](sorter/mover.py) | Turns scanned files + categorization into a `MoveOperation` plan, then executes it. Collision handling: identical content (SHA-256) is skipped as a duplicate; differing content is auto-renamed (`file (1).pdf`). Dry-run and execute share the same planning code path. |
| [sorter/history.py](sorter/history.py) | Writes a JSON transaction ledger per run to `<target>/.sorter_history/`, and reverses a run (`undo_run`) by moving files back to their recorded source path. |
| [sorter/cli.py](sorter/cli.py) | Typer app wiring: `organize`, `undo`, `list-runs`, `init-config`. Renders `rich` tables for every preview/result. |

## Design decisions worth knowing

- **Dry-run is the default everywhere.** Both `organize` and `undo` require
  `--execute`/`-f` to touch the filesystem. This was an explicit requirement,
  not an oversight — don't "simplify" it away.
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

## Extending

- New categories/extensions: edit `config.yaml` (see `sorter/default_config.yaml`
  for the schema) — no code changes needed.
- New MIME-type fallback rules: `_MIME_MAJOR_TO_CATEGORY` / `_MIME_EXACT_TO_CATEGORY`
  in [sorter/rules.py](sorter/rules.py).
