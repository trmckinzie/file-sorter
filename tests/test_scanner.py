from __future__ import annotations

from pathlib import Path

from sorter.config import IgnoreConfig
from sorter.scanner import scan_directory
from tests.conftest import make_file


def test_scan_finds_regular_files(downloads: Path):
    make_file(downloads, "a.txt")
    make_file(downloads, "b.jpg")
    entries = scan_directory(downloads, IgnoreConfig())
    names = {e.path.name for e in entries}
    assert names == {"a.txt", "b.jpg"}


def test_scan_ignores_in_progress_downloads(downloads: Path):
    make_file(downloads, "movie.mp4.crdownload")
    make_file(downloads, "song.part")
    make_file(downloads, "installer.tmp")
    make_file(downloads, "real.pdf")
    ignore = IgnoreConfig(extensions=[".crdownload", ".part", ".tmp"])
    entries = scan_directory(downloads, ignore)
    names = {e.path.name for e in entries}
    assert names == {"real.pdf"}


def test_scan_ignores_hidden_files_by_default(downloads: Path):
    make_file(downloads, ".hidden")
    make_file(downloads, "visible.txt")
    entries = scan_directory(downloads, IgnoreConfig())
    names = {e.path.name for e in entries}
    assert names == {"visible.txt"}


def test_scan_can_include_hidden_files_when_configured(downloads: Path):
    make_file(downloads, ".hidden")
    entries = scan_directory(downloads, IgnoreConfig(hidden=False))
    names = {e.path.name for e in entries}
    assert ".hidden" in names


def test_scan_ignores_named_junk_files(downloads: Path):
    make_file(downloads, "Thumbs.db")
    make_file(downloads, "real.pdf")
    entries = scan_directory(downloads, IgnoreConfig(filenames=["Thumbs.db"]))
    names = {e.path.name for e in entries}
    assert names == {"real.pdf"}


def test_scan_is_non_recursive_by_default(downloads: Path):
    sub = downloads / "Documents"
    sub.mkdir()
    make_file(sub, "nested.pdf")
    make_file(downloads, "top.pdf")
    entries = scan_directory(downloads, IgnoreConfig())
    names = {e.path.name for e in entries}
    assert names == {"top.pdf"}


def test_scan_recursive_when_requested(downloads: Path):
    sub = downloads / "Documents"
    sub.mkdir()
    make_file(sub, "nested.pdf")
    make_file(downloads, "top.pdf")
    entries = scan_directory(downloads, IgnoreConfig(), recursive=True)
    names = {e.path.name for e in entries}
    assert names == {"top.pdf", "nested.pdf"}


def test_scan_raises_for_missing_directory(tmp_path: Path):
    import pytest

    with pytest.raises(NotADirectoryError):
        scan_directory(tmp_path / "nope", IgnoreConfig())
