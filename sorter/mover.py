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
from typing import Callable, Optional

from sorter.paths import escapes_target
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
    status: str  # "moved", "skipped_duplicate", "rejected_outside_target", "error", "dry_run"
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


def execute_plan(
    plan: list[MoveOperation],
    execute: bool,
    duplicate_check: bool,
    target: Path,
    on_intent: Optional[Callable[[TransactionRecord], None]] = None,
) -> list[TransactionRecord]:
    """Carry out (or simulate, if execute=False) every move in `plan`.

    Errors on individual files (permissions, locked files, etc.) are caught
    and recorded rather than aborting the whole run.

    Every operation is checked against `target` before anything on disk is
    read, hashed, created or moved: this is the one place the user's files
    are relocated in bulk, so it is the one place that must not take a
    destination on trust. `target` has no default on purpose — a containment
    check that can be skipped by omitting an argument is not a check.

    `on_intent`, when given, is called with the record for a move immediately
    *before* that move is attempted. It exists so a caller can persist a
    write-ahead journal: the returned list only becomes durable once the whole
    loop finishes, so without it an interrupted run leaves moved files with no
    record of where they came from. An exception raised by `on_intent`
    deliberately aborts the run — if the move cannot be recorded, it must not
    happen.
    """
    records: list[TransactionRecord] = []
    target_resolved = target.resolve()

    for op in plan:
        # Containment first, ahead of the dry-run branch and ahead of every
        # filesystem call below — `_resolve_collision` alone would stat and
        # SHA-256 a file at the destination, and doing that outside `target`
        # is already a leak even if no move follows. A dry run has to show
        # the rejection too: the preview is what the user decides on, so a
        # destination the real run would refuse must not preview as a move.
        #
        # Rejected, never clamped. A destination outside the target means the
        # config or the plan is wrong (or hostile); quietly rewriting it to
        # something inside would move the file somewhere nobody asked for and
        # hide the cause.
        escaped = None
        if escapes_target(op.dst, target_resolved):
            escaped = op.dst
        elif escapes_target(op.src, target_resolved):
            escaped = op.src
        if escaped is not None:
            records.append(
                TransactionRecord(
                    src=str(op.src),
                    dst=str(op.dst),
                    status="rejected_outside_target",
                    detail=f"resolves outside the target directory {target_resolved}: {escaped}",
                )
            )
            continue

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
        if on_intent is not None:
            on_intent(TransactionRecord(src=str(op.src), dst=str(resolved_dst), status="moved"))
        try:
            resolved_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(op.src), str(resolved_dst))
            records.append(TransactionRecord(src=str(op.src), dst=str(resolved_dst), status="moved"))
        except OSError as exc:
            records.append(
                TransactionRecord(src=str(op.src), dst=str(resolved_dst), status="error", detail=str(exc))
            )

    return records
