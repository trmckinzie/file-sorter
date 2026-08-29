"""Transaction ledger: records every move made during an `organize --execute`
run as JSON, and supports reversing a run via `undo`."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sorter.mover import TransactionRecord

LEDGER_DIRNAME = ".sorter_history"


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
    return path


def list_runs(history_dir: Path) -> list[str]:
    if not history_dir.is_dir():
        return []
    run_ids = [p.stem for p in history_dir.glob("*.json")]
    return sorted(run_ids)


def load_ledger(history_dir: Path, run_id: str) -> Ledger:
    path = history_dir / f"{run_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"No ledger found for run '{run_id}' in {history_dir}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Ledger(**raw)


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
