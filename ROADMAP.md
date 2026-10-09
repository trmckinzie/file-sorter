# file_sorter roadmap

Done when: the CLAUDE.md commands work on macOS as written, and `verify.sh` (ruff + pytest) is green locally and in CI on Python 3.12–3.14.

Tier: code. See `90_Meta/Dev Environment Standard.md` in the dev vault.

## Standardize
- [x] Pin the runtime in `.python-version` (3.14); `requires-python >=3.12`
- [x] Hash-pinned `requirements-dev.txt` compiled from `pyproject.toml` with uv; `.venv` rebuilt with uv
- [x] ruff (E, F, I; 130 columns, matching the existing code) and `verify.sh`
- [x] CI on 3.12/3.13/3.14, actions pinned to a SHA, `contents: read`
- [x] `dashboard.json` with `test` and `verify`
- [x] CLAUDE.md and README rewritten from Windows to macOS commands

## Harden
- [x] Containment tests made portable. The Windows-syntax escapes (`C:\…`, UNC, `D:evil`, `..\..\`) are skipped off Windows, where they are just filenames, and POSIX escapes (`../../x`, `sub/../../x`) were added, so CI on Linux still exercises the guard. The mover was probed by hand on macOS on 2026-10-09 and rejected every escape. `build_plan` keeps the full list on every OS.
- [x] Audit #44 (fsync after every journal line) closed won't-fix 2026-10-09: the tool is used on local SSD only, and per-line fsync keeps the undo ledger crash-safe

## Reach done
- [x] Committed and pushed as `20e17d4`; CI green on 3.12/3.13/3.14 on 2026-10-09. **Done line met.**
