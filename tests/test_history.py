from __future__ import annotations

from pathlib import Path

from sorter import history
from sorter.mover import TransactionRecord
from tests.conftest import make_file


def test_save_and_load_ledger_roundtrip(tmp_path: Path):
    history_dir = tmp_path / "hist"
    records = [
        TransactionRecord(src="a.txt", dst="Documents/a.txt", status="moved"),
        TransactionRecord(src="b.jpg", dst="Images/b.jpg", status="skipped_duplicate", detail="dup"),
    ]
    run_id = history.new_run_id()
    path = history.save_ledger(history_dir, run_id, tmp_path, records)

    assert path.exists()
    ledger = history.load_ledger(history_dir, run_id)
    assert ledger.run_id == run_id
    assert len(ledger.records) == 2
    assert ledger.records[0]["status"] == "moved"


def test_list_runs_returns_sorted_ids(tmp_path: Path):
    history_dir = tmp_path / "hist"
    history.save_ledger(history_dir, "20260101T000000000000", tmp_path, [])
    history.save_ledger(history_dir, "20260102T000000000000", tmp_path, [])
    runs = history.list_runs(history_dir)
    assert runs == ["20260101T000000000000", "20260102T000000000000"]


def test_list_runs_empty_when_dir_missing(tmp_path: Path):
    assert history.list_runs(tmp_path / "does_not_exist") == []


def test_latest_run_id(tmp_path: Path):
    history_dir = tmp_path / "hist"
    assert history.latest_run_id(history_dir) is None
    history.save_ledger(history_dir, "20260101T000000000000", tmp_path, [])
    history.save_ledger(history_dir, "20260102T000000000000", tmp_path, [])
    assert history.latest_run_id(history_dir) == "20260102T000000000000"


def test_load_missing_ledger_raises(tmp_path: Path):
    import pytest

    with pytest.raises(FileNotFoundError):
        history.load_ledger(tmp_path / "hist", "nope")


def test_undo_restores_moved_file(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    dest_dir = downloads / "Images"
    dest_dir.mkdir()
    moved_file = make_file(dest_dir, "photo.jpg")

    records = [TransactionRecord(src=str(downloads / "photo.jpg"), dst=str(moved_file), status="moved")]
    history_dir = downloads / ".sorter_history"
    run_id = history.new_run_id()
    history.save_ledger(history_dir, run_id, downloads, records)

    results = history.undo_run(history_dir, run_id, execute=True)

    assert results[0].status == "restored"
    assert (downloads / "photo.jpg").exists()
    assert not moved_file.exists()


def test_undo_dry_run_does_not_move_anything(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    dest_dir = downloads / "Images"
    dest_dir.mkdir(parents=True)
    moved_file = make_file(dest_dir, "photo.jpg")

    records = [TransactionRecord(src=str(downloads / "photo.jpg"), dst=str(moved_file), status="moved")]
    history_dir = downloads / ".sorter_history"
    run_id = history.new_run_id()
    history.save_ledger(history_dir, run_id, downloads, records)

    results = history.undo_run(history_dir, run_id, execute=False)

    assert results[0].status == "dry_run"
    assert moved_file.exists()
    assert not (downloads / "photo.jpg").exists()


def test_undo_skips_when_moved_file_missing(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    missing_dst = downloads / "Images" / "photo.jpg"  # never actually created

    records = [TransactionRecord(src=str(downloads / "photo.jpg"), dst=str(missing_dst), status="moved")]
    history_dir = downloads / ".sorter_history"
    run_id = history.new_run_id()
    history.save_ledger(history_dir, run_id, downloads, records)

    results = history.undo_run(history_dir, run_id, execute=True)
    assert results[0].status == "skipped_missing"


def test_undo_skips_on_conflict_at_original_location(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    dest_dir = downloads / "Images"
    dest_dir.mkdir(parents=True)
    moved_file = make_file(dest_dir, "photo.jpg")
    make_file(downloads, "photo.jpg")  # something new already occupies the original spot

    records = [TransactionRecord(src=str(downloads / "photo.jpg"), dst=str(moved_file), status="moved")]
    history_dir = downloads / ".sorter_history"
    run_id = history.new_run_id()
    history.save_ledger(history_dir, run_id, downloads, records)

    results = history.undo_run(history_dir, run_id, execute=True)
    assert results[0].status == "skipped_conflict"
    assert moved_file.exists()  # untouched


def test_undo_ignores_non_moved_records(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    records = [
        TransactionRecord(src="a.txt", dst="Documents/a.txt", status="skipped_duplicate"),
        TransactionRecord(src="b.txt", dst="Documents/b.txt", status="error", detail="boom"),
    ]
    history_dir = downloads / ".sorter_history"
    run_id = history.new_run_id()
    history.save_ledger(history_dir, run_id, downloads, records)

    results = history.undo_run(history_dir, run_id, execute=True)
    assert results == []
