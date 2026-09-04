from __future__ import annotations

from pathlib import Path

import pytest

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


# --- Crash safety: an interrupted run must still be undoable -----------------


def _crash_after(n: int, journal: Path):
    """on_intent that journals n records, then raises as a hard stop would."""
    seen = {"count": 0}

    def _on_intent(record):
        if seen["count"] >= n:
            raise KeyboardInterrupt("simulated interruption mid-run")
        history.append_journal_record(journal, record)
        seen["count"] += 1

    return _on_intent


def test_interrupted_run_is_still_undoable(tmp_path: Path):
    """The whole point of the journal: kill a run partway, undo still works."""
    from sorter.mover import MoveOperation, execute_plan

    target = tmp_path / "downloads"
    target.mkdir()
    srcs = [make_file(target, f"file{i}.txt", b"x") for i in range(5)]
    plan = [MoveOperation(src=s, dst=target / "Documents" / s.name, category="Documents", matched_by="ext") for s in srcs]

    history_dir = tmp_path / "hist"
    run_id = history.new_run_id()
    journal = history.start_journal(history_dir, run_id, target)

    # Interrupt after 3 files have been journalled.
    try:
        execute_plan(plan, execute=True, duplicate_check=False, target=target, on_intent=_crash_after(3, journal))
    except KeyboardInterrupt:
        pass

    # No completed ledger was ever written.
    assert not (history_dir / f"{run_id}.json").exists()

    # But the run is still discoverable and loadable from its journal.
    assert run_id in history.list_runs(history_dir)
    ledger = history.load_ledger(history_dir, run_id)
    assert len(ledger.records) == 3

    # And the moved files actually go back where they came from.
    results = history.undo_run(history_dir, run_id, execute=True)
    assert [r.status for r in results] == ["restored"] * 3
    for s in srcs[:3]:
        assert s.exists(), f"{s.name} was not restored"


def test_journal_records_intent_before_the_move(tmp_path: Path):
    """A record must be durable before its move, never after."""
    from sorter.mover import MoveOperation, execute_plan

    target = tmp_path / "downloads"
    target.mkdir()
    src = make_file(target, "only.txt", b"x")
    history_dir = tmp_path / "hist"
    run_id = history.new_run_id()
    journal = history.start_journal(history_dir, run_id, target)

    observed = {}

    def _on_intent(record):
        # At this instant the move has not happened yet.
        observed["src_still_in_place"] = Path(record.src).exists()
        history.append_journal_record(journal, record)
        observed["journal_on_disk"] = journal.read_text(encoding="utf-8").count("\n") == 2

    execute_plan(
        [MoveOperation(src=src, dst=target / "Documents" / src.name, category="Documents", matched_by="ext")],
        execute=True,
        duplicate_check=False,
        target=target,
        on_intent=_on_intent,
    )

    assert observed["src_still_in_place"] is True
    assert observed["journal_on_disk"] is True


def test_completed_run_discards_its_journal(tmp_path: Path):
    history_dir = tmp_path / "hist"
    run_id = history.new_run_id()
    history.start_journal(history_dir, run_id, tmp_path)
    assert history.journal_path(history_dir, run_id).exists()

    history.save_ledger(history_dir, run_id, tmp_path, [])

    assert not history.journal_path(history_dir, run_id).exists()
    assert history.list_runs(history_dir) == [run_id]


# --- Path containment: a tampered ledger/journal must not escape target -----
# See #40 in the 2026-09 security audit: undo_run trusted src/dst paths read
# verbatim from ledger JSON with no check they stayed inside the run's target,
# making `undo --execute` an arbitrary file-move primitive against a tampered
# ledger. Covered against both the .json ledger and the .jsonl journal
# fallback, since both feed undo_run through the same code path.


def test_undo_rejects_record_outside_target_via_ledger(tmp_path: Path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = make_file(outside, "secret.txt", b"sensitive content")
    exfil_dst = outside / "exfil" / "secret_moved.txt"  # need not exist yet

    # A hand-crafted record: dst points at a real file entirely outside the
    # run's target, src points at an arbitrary new location to exfiltrate it
    # to. This is exactly the shape of ledger tampering the audit's PoC used.
    records = [TransactionRecord(src=str(exfil_dst), dst=str(victim), status="moved")]
    history_dir = downloads / ".sorter_history"
    run_id = history.new_run_id()
    history.save_ledger(history_dir, run_id, downloads, records)

    results = history.undo_run(history_dir, run_id, execute=True)

    assert results[0].status == "rejected_outside_target"
    assert victim.exists()
    assert victim.read_bytes() == b"sensitive content"
    assert not exfil_dst.exists()


def test_undo_rejects_record_outside_target_via_journal_fallback(tmp_path: Path):
    """Same tampering, but reaching undo_run only through the crash-safety
    journal (no completed .json ledger) — proves the fallback path is
    covered by the same containment check, not just the normal ledger."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = make_file(outside, "secret.txt", b"sensitive content")
    exfil_dst = outside / "exfil" / "secret_moved.txt"

    history_dir = downloads / ".sorter_history"
    run_id = history.new_run_id()
    journal = history.start_journal(history_dir, run_id, downloads)
    history.append_journal_record(
        journal, TransactionRecord(src=str(exfil_dst), dst=str(victim), status="moved")
    )
    # Deliberately no save_ledger call: only the .jsonl exists, so
    # load_ledger must fall back to load_journal to find this record at all.
    assert not (history_dir / f"{run_id}.json").exists()

    results = history.undo_run(history_dir, run_id, execute=True)

    assert results[0].status == "rejected_outside_target"
    assert victim.exists()
    assert victim.read_bytes() == b"sensitive content"
    assert not exfil_dst.exists()


def test_undo_rejects_symlink_whose_real_target_escapes(tmp_path: Path):
    """dst is a symlink living inside target, but it points somewhere else
    entirely. resolve() follows the link, so this must be rejected too —
    otherwise a tampered ledger could launder an escape through a symlink
    planted inside target instead of a literal outside path."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    real_secret = make_file(outside, "secret.txt", b"sensitive content")

    dest_dir = downloads / "Images"
    dest_dir.mkdir()
    symlink_path = dest_dir / "photo.jpg"
    try:
        symlink_path.symlink_to(real_secret)
    except OSError as exc:
        pytest.skip(f"cannot create symlinks in this environment: {exc}")

    records = [TransactionRecord(src=str(downloads / "photo.jpg"), dst=str(symlink_path), status="moved")]
    history_dir = downloads / ".sorter_history"
    run_id = history.new_run_id()
    history.save_ledger(history_dir, run_id, downloads, records)

    results = history.undo_run(history_dir, run_id, execute=True)

    assert results[0].status == "rejected_outside_target"
    assert real_secret.exists()
    assert real_secret.read_bytes() == b"sensitive content"


def test_undo_still_restores_legitimate_record_after_containment_check(tmp_path: Path):
    """Regression: the new containment check must not reject an ordinary,
    untampered ledger — everything inside target still restores as before."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    dest_dir = downloads / "Documents"
    dest_dir.mkdir()
    moved_file = make_file(dest_dir, "report.pdf", b"contents")

    records = [TransactionRecord(src=str(downloads / "report.pdf"), dst=str(moved_file), status="moved")]
    history_dir = downloads / ".sorter_history"
    run_id = history.new_run_id()
    history.save_ledger(history_dir, run_id, downloads, records)

    results = history.undo_run(history_dir, run_id, execute=True)

    assert results[0].status == "restored"
    assert (downloads / "report.pdf").exists()
    assert (downloads / "report.pdf").read_bytes() == b"contents"
    assert not moved_file.exists()


def test_torn_final_line_recovers_earlier_records(tmp_path: Path):
    """A crash mid-write leaves a partial line; earlier records must survive."""
    history_dir = tmp_path / "hist"
    run_id = history.new_run_id()
    journal = history.start_journal(history_dir, run_id, tmp_path)
    history.append_journal_record(journal, TransactionRecord(src="a.txt", dst="D/a.txt", status="moved"))
    with journal.open("a", encoding="utf-8") as fh:
        fh.write('{"record": {"src": "b.txt", "ds')  # truncated

    ledger = history.load_ledger(history_dir, run_id)
    assert len(ledger.records) == 1
    assert ledger.records[0]["src"] == "a.txt"


def test_journal_reports_count_of_dropped_records(tmp_path: Path):
    """See #43 in the 2026-09 security audit: a corrupted line anywhere in
    the journal (not just a torn trailing one) was silently dropped with no
    signal. load_journal must now surface how many lines it lost."""
    history_dir = tmp_path / "hist"
    run_id = history.new_run_id()
    journal = history.start_journal(history_dir, run_id, tmp_path)
    history.append_journal_record(journal, TransactionRecord(src="a.txt", dst="D/a.txt", status="moved"))
    with journal.open("a", encoding="utf-8") as fh:
        fh.write('{"record": {"src": "corrupted", "ds\n')  # a corrupted middle line
    history.append_journal_record(journal, TransactionRecord(src="b.txt", dst="D/b.txt", status="moved"))

    ledger = history.load_ledger(history_dir, run_id)
    assert len(ledger.records) == 2
    assert ledger.dropped_records == 1


def test_ledger_from_completed_run_has_zero_dropped_records(tmp_path: Path):
    """Regression: a normal .json ledger (no journal lines involved) must
    report dropped_records == 0, not fail to load."""
    history_dir = tmp_path / "hist"
    run_id = history.new_run_id()
    history.save_ledger(history_dir, run_id, tmp_path, [TransactionRecord(src="a", dst="b", status="moved")])

    ledger = history.load_ledger(history_dir, run_id)
    assert ledger.dropped_records == 0
