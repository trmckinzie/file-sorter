"""Directory scanning: finds candidate files and filters out anything
that should never be touched (in-progress downloads, junk, hidden files)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sorter.config import IgnoreConfig


@dataclass(frozen=True)
class FileEntry:
    path: Path
    size: int
    mtime: float


def _is_ignored(path: Path, ignore: IgnoreConfig) -> bool:
    if ignore.hidden and path.name.startswith("."):
        return True
    if path.name in ignore.filenames:
        return True
    if path.suffix.lower() in ignore.extensions:
        return True
    return False


def scan_directory(target: Path, ignore: IgnoreConfig, recursive: bool = False) -> list[FileEntry]:
    """Return files directly inside `target` that are safe to consider for
    organizing.

    Non-recursive by default: only files sitting directly in `target` are
    scanned. This is deliberate — once files are sorted into category
    subfolders, we don't want subsequent runs to reach back into those
    subfolders and re-shuffle already-organized files.
    """
    if not target.is_dir():
        raise NotADirectoryError(f"Target is not a directory: {target}")

    target_resolved = target.resolve()
    iterator = target.rglob("*") if recursive else target.iterdir()

    entries: list[FileEntry] = []
    for path in iterator:
        if not path.is_file():
            continue
        if _is_ignored(path, ignore):
            continue
        try:
            stat = path.stat()
            resolved = path.resolve()
        except OSError:
            # File vanished or is locked/inaccessible mid-scan; skip it.
            continue
        # A directory junction/reparse point or symlink planted inside
        # target can make an entry's *real* location fall outside it (only
        # reachable via rglob, i.e. recursive=True, since iterdir doesn't
        # descend into a junction to find files beneath it) — never bring an
        # external file into the plan just because it's reachable through a
        # link. See #41 in the 2026-09 security audit.
        if resolved != target_resolved and target_resolved not in resolved.parents:
            continue
        entries.append(FileEntry(path=path, size=stat.st_size, mtime=stat.st_mtime))

    return entries
