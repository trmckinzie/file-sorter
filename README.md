# file-sorter

Safely organize a cluttered directory (e.g. `~/Downloads`) into category
folders by extension/MIME type, with dry-run previews, duplicate detection,
and a JSON undo ledger.

See [CLAUDE.md](CLAUDE.md) for architecture, setup, and usage details.

## Quick start

```bash
uv venv --python 3.14
uv pip install --python .venv/bin/python -r requirements-dev.txt
uv pip install --python .venv/bin/python --no-deps -e .

# Preview (default, no files touched)
.venv/bin/python -m sorter.cli organize ~/Downloads

# Apply
.venv/bin/python -m sorter.cli organize ~/Downloads --execute

# Undo the last run
.venv/bin/python -m sorter.cli undo --target ~/Downloads --execute
```
