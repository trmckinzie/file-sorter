"""Typer CLI entry point for file-sorter."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from sorter import history
from sorter.config import load_config
from sorter.mover import build_plan, execute_plan
from sorter.rules import RuleEngine
from sorter.scanner import scan_directory

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Safely organize a cluttered directory (e.g. ~/Downloads) into category folders.",
)
console = Console()
error_console = Console(stderr=True, style="bold red")

DEFAULT_TARGET = Path.home() / "Downloads"

_STATUS_STYLE = {
    "moved": "green",
    "dry_run": "yellow",
    "skipped_duplicate": "cyan",
    "error": "bold red",
    "restored": "green",
    "skipped_missing": "cyan",
    "skipped_conflict": "cyan",
}


@app.command()
def organize(
    target: Path = typer.Argument(DEFAULT_TARGET, help="Directory to organize."),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Path to a config.yaml. Defaults to the bundled config."),
    execute: bool = typer.Option(
        False, "--execute", "-f", help="Actually move files. Without this flag, only a dry-run preview is shown."
    ),
    recursive: bool = typer.Option(False, "--recursive", help="Recurse into subdirectories of the target (off by default)."),
    by_date: Optional[bool] = typer.Option(
        None, "--by-date/--no-by-date", help="Override date_routing.enabled from the config file."
    ),
    history_dir: Optional[Path] = typer.Option(
        None, "--history-dir", help="Where to write the undo ledger. Defaults to <target>/.sorter_history."
    ),
) -> None:
    """Preview (default) or execute organizing TARGET into category folders."""
    target = target.expanduser().resolve()

    try:
        cfg = load_config(config)
    except Exception as exc:  # noqa: BLE001 - surface any config error to the user
        error_console.print(f"Failed to load config: {exc}")
        raise typer.Exit(code=1)

    if by_date is not None:
        cfg.date_routing.enabled = by_date

    try:
        entries = scan_directory(target, cfg.ignore, recursive=recursive)
    except NotADirectoryError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1)

    if not entries:
        console.print(f"No files to organize in [bold]{target}[/bold].")
        raise typer.Exit(code=0)

    rule_engine = RuleEngine(cfg)
    plan = build_plan(entries, rule_engine, target)

    if not plan:
        console.print(f"Found {len(entries)} file(s), but none matched a category (and no fallback is configured).")
        raise typer.Exit(code=0)

    # Open the journal before the first move, not after the last one: a run
    # interrupted partway is exactly when the undo record matters, and a ledger
    # written only at the end would not exist yet.
    resolved_history_dir = None
    run_id = None
    on_intent = None
    if execute:
        resolved_history_dir = history_dir or history.default_history_dir(target)
        run_id = history.new_run_id()
        journal = history.start_journal(resolved_history_dir, run_id, target)
        on_intent = lambda record: history.append_journal_record(journal, record)  # noqa: E731

    records = execute_plan(
        plan, execute=execute, duplicate_check=cfg.duplicate_check, on_intent=on_intent
    )

    _render_table(records, execute=execute)

    if execute:
        ledger_path = history.save_ledger(resolved_history_dir, run_id, target, records)
        moved = sum(1 for r in records if r.status == "moved")
        console.print(f"\n[bold green]{moved}[/bold green] file(s) moved. Ledger written to [bold]{ledger_path}[/bold].")
        console.print(f"Run ID: [bold]{run_id}[/bold] (use 'file-sorter undo {run_id}' to reverse this run)")
    else:
        console.print(f"\n[yellow]Dry run[/yellow] — {len(plan)} file(s) would be moved. Re-run with --execute to apply.")


def _render_table(records, execute: bool) -> None:
    table = Table(show_lines=False)
    table.add_column("Source", overflow="fold")
    table.add_column("Destination", overflow="fold")
    table.add_column("Status")
    if not execute:
        # In dry-run mode every record is "dry_run"; render status as
        # "would move" for clarity instead of the raw internal name.
        for record in records:
            table.add_row(record.src, record.dst, "[yellow]would move[/yellow]")
    else:
        for record in records:
            style = _STATUS_STYLE.get(record.status, "white")
            status_text = record.status if not record.detail else f"{record.status} ({record.detail})"
            table.add_row(record.src, record.dst, f"[{style}]{status_text}[/{style}]")
    console.print(table)


@app.command()
def undo(
    run_id: Optional[str] = typer.Argument(None, help="Run ID to undo. Defaults to the most recent run."),
    target: Path = typer.Option(DEFAULT_TARGET, "--target", "-t", help="Directory the original run organized."),
    history_dir: Optional[Path] = typer.Option(
        None, "--history-dir", help="Ledger location. Defaults to <target>/.sorter_history."
    ),
    execute: bool = typer.Option(
        False, "--execute", "-f", help="Actually restore files. Without this flag, only a dry-run preview is shown."
    ),
) -> None:
    """Reverse the moves made by a previous `organize --execute` run."""
    target = target.expanduser().resolve()
    resolved_history_dir = history_dir or history.default_history_dir(target)

    resolved_run_id = run_id or history.latest_run_id(resolved_history_dir)
    if resolved_run_id is None:
        error_console.print(f"No runs found in {resolved_history_dir}.")
        raise typer.Exit(code=1)

    try:
        ledger = history.load_ledger(resolved_history_dir, resolved_run_id)
    except FileNotFoundError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1)

    if ledger.dropped_records:
        error_console.print(
            f"[yellow]Warning:[/yellow] {ledger.dropped_records} journal record(s) for run "
            f"[bold]{resolved_run_id}[/bold] were corrupted and could not be recovered — "
            "undo coverage for this run may be incomplete."
        )

    try:
        results = history.undo_run(resolved_history_dir, resolved_run_id, execute=execute)
    except FileNotFoundError as exc:
        error_console.print(str(exc))
        raise typer.Exit(code=1)

    if not results:
        console.print(f"Nothing to undo for run [bold]{resolved_run_id}[/bold] (no moved files recorded).")
        raise typer.Exit(code=0)

    table = Table(show_lines=False)
    table.add_column("Restore to (original)", overflow="fold")
    table.add_column("Current location", overflow="fold")
    table.add_column("Status")
    for r in results:
        style = _STATUS_STYLE.get(r.status, "white")
        status_text = r.status if not r.detail else f"{r.status} ({r.detail})"
        table.add_row(r.src, r.dst, f"[{style}]{status_text}[/{style}]")
    console.print(table)

    if execute:
        restored = sum(1 for r in results if r.status == "restored")
        console.print(f"\n[bold green]{restored}[/bold green] file(s) restored for run [bold]{resolved_run_id}[/bold].")
    else:
        console.print(f"\n[yellow]Dry run[/yellow] — re-run with --execute to actually restore these files.")


@app.command("list-runs")
def list_runs_cmd(
    target: Path = typer.Option(DEFAULT_TARGET, "--target", "-t", help="Directory to look up run history for."),
    history_dir: Optional[Path] = typer.Option(None, "--history-dir"),
) -> None:
    """List available run IDs that can be passed to `undo`."""
    target = target.expanduser().resolve()
    resolved_history_dir = history_dir or history.default_history_dir(target)
    runs = history.list_runs(resolved_history_dir)
    if not runs:
        console.print(f"No runs found in {resolved_history_dir}.")
        raise typer.Exit(code=0)
    for run_id in runs:
        console.print(run_id)


@app.command("init-config")
def init_config(
    output: Path = typer.Argument(Path("config.yaml"), help="Where to write the editable config file."),
) -> None:
    """Write a copy of the default config to OUTPUT for customization."""
    from sorter.config import load_default_config_text

    output = output.expanduser().resolve()
    if output.exists():
        error_console.print(f"{output} already exists; refusing to overwrite it.")
        raise typer.Exit(code=1)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(load_default_config_text(), encoding="utf-8")
    console.print(f"Wrote default config to [bold]{output}[/bold].")


if __name__ == "__main__":
    app()
