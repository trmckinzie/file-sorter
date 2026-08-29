"""Move planning and execution, with collision resolution and error handling.

Nothing in this module touches the filesystem destructively unless
`execute=True` is passed to `execute_plan` — building a plan is always safe
and is what powers the dry-run preview.
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sorter.rules import Categorization, RuleEngine
from sorter.scanner import FileEntry


@dataclass
class MoveOperation:
    src: Path
    dst: Path
    category: str
    matched_by: str


@dataclass
class TransactionRecord:
    src: str
    dst: str
    status: str  # "moved", "skipped_duplicate", "error", "dry_run"
    detail: Optional[str] = None


def build_plan(entries: list[FileEntry], rule_engine: RuleEngine, target: Path) -> list[MoveOperation]:
    """Resolve a category (and optional date subfolder) for every scanned
    file. Files with no matching category (and no fallback configured) are
    left out of the plan entirely."""
    plan: list[MoveOperation] = []
    for entry in entries:
        result: Categorization = rule_engine.categorize(entry.path)
        if result.category is None:
            continue

        dest_dir = target / result.category
        if result.subfolder:
            dest_dir = dest_dir / result.subfolder

        plan.append(
            MoveOperation(
                src=entry.path,
                dst=dest_dir / entry.path.name,
                category=result.category,
                matched_by=result.matched_by,
            )
        )
    return plan


def _sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_collision(src: Path, dst: Path, duplicate_check: bool) -> tuple[Optional[Path], Optional[str]]:
    """Return (resolved_dst, skip_reason). If skip_reason is set, the move
    should be skipped and resolved_dst is None."""
    if not dst.exists():
        return dst, None

    if duplicate_check:
        try:
            if _sha256(src) == _sha256(dst):
                return None, f"duplicate of existing file at {dst}"
        except OSError:
            # Can't hash (e.g. permissions) — fall through to renaming
            # rather than silently dropping the file.
            pass

    return _auto_rename(dst), None


def _auto_rename(dst: Path) -> Path:
    stem, suffix, parent = dst.stem, dst.suffix, dst.parent
    counter = 1
    candidate = dst
    while candidate.exists():
        candidate = parent / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def execute_plan(plan: list[MoveOperation], execute: bool, duplicate_check: bool) -> list[TransactionRecord]:
    """Carry out (or simulate, if execute=False) every move in `plan`.

    Errors on individual files (permissions, locked files, etc.) are caught
    and recorded rather than aborting the whole run.
    """
    records: list[TransactionRecord] = []

    for op in plan:
        if not execute:
            records.append(TransactionRecord(src=str(op.src), dst=str(op.dst), status="dry_run"))
            continue

        try:
            resolved_dst, skip_reason = _resolve_collision(op.src, op.dst, duplicate_check)
        except OSError as exc:
            records.append(TransactionRecord(src=str(op.src), dst=str(op.dst), status="error", detail=str(exc)))
            continue

        if skip_reason is not None:
            records.append(
                TransactionRecord(src=str(op.src), dst=str(op.dst), status="skipped_duplicate", detail=skip_reason)
            )
            continue

        assert resolved_dst is not None
        try:
            resolved_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(op.src), str(resolved_dst))
            records.append(TransactionRecord(src=str(op.src), dst=str(resolved_dst), status="moved"))
        except OSError as exc:
            records.append(
                TransactionRecord(src=str(op.src), dst=str(resolved_dst), status="error", detail=str(exc))
            )

    return records
