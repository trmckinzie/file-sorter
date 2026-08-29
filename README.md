# file-sorter

Safely organize a cluttered directory (e.g. `~/Downloads`) into category
folders by extension/MIME type, with dry-run previews, duplicate detection,
and a JSON undo ledger.

See [CLAUDE.md](CLAUDE.md) for architecture, setup, and usage details.

## Quick start

```bash
py -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# Preview (default, no files touched)
.venv\Scripts\python.exe -m sorter.cli organize ~/Downloads

# Apply
.venv\Scripts\python.exe -m sorter.cli organize ~/Downloads --execute

# Undo the last run
.venv\Scripts\python.exe -m sorter.cli undo --target ~/Downloads --execute
```
