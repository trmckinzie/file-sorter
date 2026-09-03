"""Transaction ledger: records every move made during an `organize --execute`
run as JSON, and supports reversing a run via `undo`."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sorter.mover import TransactionRecord

LEDGER_DIRNAME = ".sorter_history"
JOURNAL_SUFFIX = ".jsonl"


@dataclass
class Ledger:
    run_id: str
    target: str
    created_at: str
    records: list[dict] = field(default_factory=list)


def default_history_dir(target: Path) -> Path:
    return target / LEDGER_DIRNAME


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")


def journal_path(history_dir: Path, run_id: str) -> Path:
    return history_dir / f"{run_id}{JOURNAL_SUFFIX}"


def start_journal(history_dir: Path, run_id: str, target: Path) -> Path:
    """Open a write-ahead journal for `run_id` and write its header line.

    The final `<run_id>.json` ledger is only durable once a whole run finishes,
    so on its own it cannot survive a run that is interrupted partway — and an
    interrupted run is exactly when an undo matters most. The journal records
    each move *before* it is attempted, which means a crash can leave a record
    for a move that never happened, but never a move with no record.

    That asymmetry is deliberate: `undo_run` already reports a file that isn't
    where the record says as `skipped_missing`, so a spurious record is
    harmless, while a missing one strands a file with no recorded way back.
    """
    history_dir.mkdir(parents=True, exist_ok=True)
    path = journal_path(history_dir, run_id)
    _append_line(
        path,
        {
            "header": {
                "run_id": run_id,
                "target": str(target),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    return path


def append_journal_record(path: Path, record: TransactionRecord) -> None:
    _append_line(path, {"record": asdict(record)})


def _append_line(path: Path, payload: dict) -> None:
    # fsync per line: the point of the journal is surviving a hard stop, and a
    # buffered write that never reached disk would defeat it. Moves dominate the
    # runtime here, so the extra flush is not the bottleneck.
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def load_journal(history_dir: Path, run_id: str) -> Optional[Ledger]:
    """Rebuild a Ledger from an interrupted run's journal, or None if absent."""
    path = journal_path(history_dir, run_id)
    if not path.is_file():
        return None

    header: dict = {}
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            # A torn final line from a crash mid-write. Every earlier line is
            # still complete, so recover what we can rather than losing the run.
            continue
        if "header" in payload:
            header = payload["header"]
        elif "record" in payload:
            records.append(payload["record"])

    return Ledger(
        run_id=header.get("run_id", run_id),
        target=header.get("target", ""),
        created_at=header.get("created_at", ""),
        records=records,
    )


def save_ledger(history_dir: Path, run_id: str, target: Path, records: list[TransactionRecord]) -> Path:
    history_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(
        run_id=run_id,
        target=str(target),
        created_at=datetime.now(timezone.utc).isoformat(),
        records=[asdict(r) for r in records],
    )
    path = history_dir / f"{run_id}.json"
    path.write_text(json.dumps(asdict(ledger), indent=2), encoding="utf-8")
    # The completed ledger carries true per-file outcomes and supersedes the
    # optimistic journal, so drop it rather than leaving two records of one run.
    journal_path(history_dir, run_id).unlink(missing_ok=True)
    return path


def list_runs(history_dir: Path) -> list[str]:
    if not history_dir.is_dir():
        return []
    run_ids = {p.stem for p in history_dir.glob("*.json")}
    # Interrupted runs have only a journal; they are still undoable, so they
    # must show up here or `undo` with no run id will skip straight past them.
    run_ids |= {p.stem for p in history_dir.glob(f"*{JOURNAL_SUFFIX}")}
    return sorted(run_ids)


def load_ledger(history_dir: Path, run_id: str) -> Ledger:
    path = history_dir / f"{run_id}.json"
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Ledger(**raw)

    recovered = load_journal(history_dir, run_id)
    if recovered is not None:
        return recovered

    raise FileNotFoundError(f"No ledger found for run '{run_id}' in {history_dir}")


def latest_run_id(history_dir: Path) -> Optional[str]:
    runs = list_runs(history_dir)
    return runs[-1] if runs else None


@dataclass
class UndoRecord:
    src: str  # original location, i.e. where the file will be restored to
    dst: str  # location it currently occupies (the moved-to path)
    status: str  # "restored", "skipped_missing", "skipped_conflict", "error", "dry_run"
    detail: Optional[str] = None


def undo_run(history_dir: Path, run_id: str, execute: bool) -> list[UndoRecord]:
    ledger = load_ledger(history_dir, run_id)
    results: list[UndoRecord] = []

    # Reverse order so that if multiple files ended up interdependent in
    # naming (unlikely, but cheap to guard), we unwind most-recent-first.
    for raw in reversed(ledger.records):
        record = TransactionRecord(**raw)
        if record.status != "moved":
            continue  # nothing to undo for skipped/error/dry_run entries

        moved_to = Path(record.dst)
        original = Path(record.src)

        if not execute:
            results.append(UndoRecord(src=str(original), dst=str(moved_to), status="dry_run"))
            continue

        if not moved_to.exists():
            results.append(
                UndoRecord(
                    src=str(original),
                    dst=str(moved_to),
                    status="skipped_missing",
                    detail="file no longer exists at its moved-to location",
                )
            )
            continue

        if original.exists():
            results.append(
                UndoRecord(
                    src=str(original),
                    dst=str(moved_to),
                    status="skipped_conflict",
                    detail="a file already exists at the original location",
                )
            )
            continue

        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(moved_to), str(original))
            results.append(UndoRecord(src=str(original), dst=str(moved_to), status="restored"))
        except OSError as exc:
            results.append(UndoRecord(src=str(original), dst=str(moved_to), status="error", detail=str(exc)))

    return results
