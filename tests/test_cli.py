from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from sorter.cli import app
from tests.conftest import make_file

runner = CliRunner()


def test_organize_dry_run_by_default(downloads: Path):
    f = make_file(downloads, "photo.jpg")
    result = runner.invoke(app, ["organize", str(downloads)])

    assert result.exit_code == 0
    assert "Dry run" in result.stdout
    assert f.exists()
    assert not (downloads / "Images" / "photo.jpg").exists()


def test_organize_execute_moves_files_and_writes_ledger(downloads: Path):
    make_file(downloads, "photo.jpg")
    result = runner.invoke(app, ["organize", str(downloads), "--execute"])

    assert result.exit_code == 0
    assert (downloads / "Images" / "photo.jpg").exists()
    assert "Ledger written" in result.stdout

    runs = list((downloads / ".sorter_history").glob("*.json"))
    assert len(runs) == 1


def test_organize_reports_when_nothing_to_do(downloads: Path):
    result = runner.invoke(app, ["organize", str(downloads)])
    assert result.exit_code == 0
    assert "No files to organize" in result.stdout


def test_organize_missing_target_errors(tmp_path: Path):
    result = runner.invoke(app, ["organize", str(tmp_path / "nope")])
    assert result.exit_code == 1


def test_organize_with_custom_config(downloads: Path, tmp_path: Path):
    config_path = tmp_path / "custom.yaml"
    config_path.write_text(
        'categories:\n  Notes:\n    extensions: [".note"]\nfallback_category: null\n',
        encoding="utf-8",
    )
    make_file(downloads, "todo.note")
    result = runner.invoke(app, ["organize", str(downloads), "--execute", "--config", str(config_path)])

    assert result.exit_code == 0
    assert (downloads / "Notes" / "todo.note").exists()


def test_undo_roundtrip_via_cli(downloads: Path):
    make_file(downloads, "photo.jpg")
    runner.invoke(app, ["organize", str(downloads), "--execute"])
    assert (downloads / "Images" / "photo.jpg").exists()

    result = runner.invoke(app, ["undo", "--target", str(downloads), "--execute"])
    assert result.exit_code == 0
    assert "restored" in result.stdout.lower() or "1" in result.stdout
    assert (downloads / "photo.jpg").exists()
    assert not (downloads / "Images" / "photo.jpg").exists()


def test_undo_dry_run_via_cli_does_not_restore(downloads: Path):
    make_file(downloads, "photo.jpg")
    runner.invoke(app, ["organize", str(downloads), "--execute"])

    result = runner.invoke(app, ["undo", "--target", str(downloads)])
    assert result.exit_code == 0
    assert (downloads / "Images" / "photo.jpg").exists()
    assert not (downloads / "photo.jpg").exists()


def test_undo_with_no_runs_errors(downloads: Path):
    result = runner.invoke(app, ["undo", "--target", str(downloads)])
    assert result.exit_code == 1


def test_undo_warns_when_journal_had_dropped_records(downloads: Path):
    """See #43 in the 2026-09 security audit: undo must surface a warning
    when the run it's restoring was recovered from a journal that lost a
    record, instead of silently reporting partial coverage as complete."""
    from sorter import history
    from sorter.mover import TransactionRecord

    run_id = history.new_run_id()
    history_dir = downloads / ".sorter_history"
    journal = history.start_journal(history_dir, run_id, downloads)
    history.append_journal_record(journal, TransactionRecord(src="a.txt", dst="D/a.txt", status="moved"))
    with journal.open("a", encoding="utf-8") as fh:
        fh.write('{"record": {"src": "corrupted", "ds\n')

    result = runner.invoke(app, ["undo", "--target", str(downloads), run_id])

    assert "Warning" in result.stderr
    assert "1 journal record" in result.stderr


def test_organize_rejects_unsafe_category_in_config(downloads: Path, tmp_path: Path):
    """A category that escapes the target must stop the run with a clear
    config error, exit non-zero, and move nothing."""
    config_path = tmp_path / "evil.yaml"
    config_path.write_text(
        'categories:\n  "C:\\\\Windows\\\\System32":\n    extensions: [".jpg"]\nfallback_category: null\n',
        encoding="utf-8",
    )
    src = make_file(downloads, "photo.jpg", b"private bytes")

    result = runner.invoke(app, ["organize", str(downloads), "--execute", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Unsafe destination in config" in result.stderr
    assert src.exists() and src.read_bytes() == b"private bytes"
    assert not (downloads / ".sorter_history").exists()


def test_organize_reports_rejected_destination_in_the_table(downloads: Path, tmp_path: Path, monkeypatch):
    """A rejection that reaches execute_plan must be *displayed*, not
    swallowed — including in a dry run, where every row used to be flattened
    to 'would move' regardless of status."""
    from sorter import cli as cli_module
    from sorter.mover import MoveOperation

    outside = tmp_path / "outside"
    outside.mkdir()
    src = make_file(downloads, "photo.jpg", b"private bytes")

    real_build_plan = cli_module.build_plan
    monkeypatch.setattr(
        cli_module,
        "build_plan",
        lambda *a, **k: [
            MoveOperation(src=src, dst=outside / "photo.jpg", category="Images", matched_by="extension")
        ],
    )
    assert real_build_plan is not cli_module.build_plan

    result = runner.invoke(app, ["organize", str(downloads)])

    assert result.exit_code == 0
    assert "rejected_outside_target" in result.stdout
    assert "would move" not in result.stdout
    assert "0 file(s) would be moved" in result.stdout
    assert "REJECTED" in result.stderr
    assert src.exists()
    assert not (outside / "photo.jpg").exists()


def test_list_runs_cli(downloads: Path):
    make_file(downloads, "photo.jpg")
    runner.invoke(app, ["organize", str(downloads), "--execute"])

    result = runner.invoke(app, ["list-runs", "--target", str(downloads)])
    assert result.exit_code == 0
    assert result.stdout.strip() != ""


def test_init_config_writes_file(tmp_path: Path):
    output = tmp_path / "my_config.yaml"
    result = runner.invoke(app, ["init-config", str(output)])
    assert result.exit_code == 0
    assert output.exists()
    assert "categories" in output.read_text(encoding="utf-8")


def test_init_config_refuses_to_overwrite(tmp_path: Path):
    output = tmp_path / "my_config.yaml"
    output.write_text("existing", encoding="utf-8")
    result = runner.invoke(app, ["init-config", str(output)])
    assert result.exit_code == 1
    assert output.read_text(encoding="utf-8") == "existing"
