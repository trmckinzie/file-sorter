from __future__ import annotations

from pathlib import Path

import pytest

from sorter.config import SorterConfig
from sorter.mover import MoveOperation, build_plan, execute_plan
from sorter.rules import RuleEngine
from sorter.scanner import scan_directory
from tests.conftest import make_file


def _plan_for(downloads: Path, cfg: SorterConfig):
    entries = scan_directory(downloads, cfg.ignore)
    engine = RuleEngine(cfg)
    return build_plan(entries, engine, downloads)


def test_dry_run_does_not_move_files(downloads: Path, default_config: SorterConfig):
    f = make_file(downloads, "photo.jpg")
    plan = _plan_for(downloads, default_config)
    records = execute_plan(plan, execute=False, duplicate_check=default_config.duplicate_check, target=downloads)

    assert f.exists()
    assert all(r.status == "dry_run" for r in records)


def test_execute_moves_file_into_category_folder(downloads: Path, default_config: SorterConfig):
    f = make_file(downloads, "photo.jpg")
    plan = _plan_for(downloads, default_config)
    records = execute_plan(plan, execute=True, duplicate_check=default_config.duplicate_check, target=downloads)

    assert not f.exists()
    dest = downloads / "Images" / "photo.jpg"
    assert dest.exists()
    assert records[0].status == "moved"
    assert records[0].dst == str(dest)


def test_collision_with_different_content_is_renamed(downloads: Path, default_config: SorterConfig):
    (downloads / "Images").mkdir()
    make_file(downloads / "Images", "photo.jpg", content=b"existing-content")
    make_file(downloads, "photo.jpg", content=b"new-content")

    plan = _plan_for(downloads, default_config)
    records = execute_plan(plan, execute=True, duplicate_check=True, target=downloads)

    assert records[0].status == "moved"
    renamed = downloads / "Images" / "photo (1).jpg"
    assert renamed.exists()
    assert renamed.read_bytes() == b"new-content"
    # original destination file is untouched
    assert (downloads / "Images" / "photo.jpg").read_bytes() == b"existing-content"


def test_collision_with_identical_content_is_skipped_as_duplicate(downloads: Path, default_config: SorterConfig):
    (downloads / "Images").mkdir()
    make_file(downloads / "Images", "photo.jpg", content=b"same-bytes")
    src = make_file(downloads, "photo.jpg", content=b"same-bytes")

    plan = _plan_for(downloads, default_config)
    records = execute_plan(plan, execute=True, duplicate_check=True, target=downloads)

    assert records[0].status == "skipped_duplicate"
    # source file is left in place, nothing was deleted
    assert src.exists()


def test_collision_without_duplicate_check_always_renames(downloads: Path, default_config: SorterConfig):
    (downloads / "Images").mkdir()
    make_file(downloads / "Images", "photo.jpg", content=b"same-bytes")
    make_file(downloads, "photo.jpg", content=b"same-bytes")

    plan = _plan_for(downloads, default_config)
    records = execute_plan(plan, execute=True, duplicate_check=False, target=downloads)

    assert records[0].status == "moved"
    assert (downloads / "Images" / "photo (1).jpg").exists()


def test_multiple_collisions_increment_counter(downloads: Path, default_config: SorterConfig):
    (downloads / "Images").mkdir()
    make_file(downloads / "Images", "photo.jpg", content=b"one")
    make_file(downloads / "Images", "photo (1).jpg", content=b"two")
    make_file(downloads, "photo.jpg", content=b"three")

    plan = _plan_for(downloads, default_config)
    records = execute_plan(plan, execute=True, duplicate_check=True, target=downloads)

    assert records[0].status == "moved"
    assert (downloads / "Images" / "photo (2).jpg").exists()


def test_files_with_no_matching_category_are_excluded_from_plan(downloads: Path):
    cfg = SorterConfig.model_validate({"categories": {}, "fallback_category": None})
    make_file(downloads, "mystery.xyz123")
    plan = _plan_for(downloads, cfg)
    assert plan == []


def test_date_routing_creates_nested_destination(downloads: Path):
    cfg = SorterConfig.model_validate(
        {
            "categories": {"Documents": {"extensions": [".pdf"]}},
            "date_routing": {"enabled": True, "format": "%Y"},
        }
    )
    make_file(downloads, "report.pdf")
    plan = _plan_for(downloads, cfg)
    execute_plan(plan, execute=True, duplicate_check=True, target=downloads)

    year = plan[0].dst.parent.name
    assert (downloads / "Documents" / year / "report.pdf").exists()


# --- Path containment: execute_plan must not move files out of target ------
# The bulk-move path had no containment check at all — only `undo_run` did,
# which is backwards, since `execute_plan` is what actually relocates the
# user's files. `Path("C:/target") / "C:/Windows/System32"` evaluates to
# `C:/Windows/System32` on Windows: an absolute right-hand side silently
# discards the base, so a hostile or broken category name (or a
# `date_routing.format` full of `..`) sent files anywhere the process could
# write. Follow-up to #40 in the 2026-09 security audit, which fixed the
# same class of hole in `undo_run` only.
#
# These build the plan by hand rather than via `build_plan`, which now
# rejects such categories up front (see test_build_plan_* below): the point
# here is that the mover refuses the move even if a bad plan reaches it.


def _op(src: Path, dst: Path, category: str) -> MoveOperation:
    return MoveOperation(src=src, dst=dst, category=category, matched_by="extension")


ESCAPING_CATEGORIES = [
    pytest.param(r"C:\Windows\System32", id="absolute-windows"),
    pytest.param(r"\\host\share", id="unc"),
    pytest.param(r"\\evilhost\exfil", id="unc-exfil"),
    pytest.param(r"\\?\C:\Windows", id="device-path"),
    pytest.param("D:evil", id="drive-relative-other-drive"),
    pytest.param(r"..\..\Windows", id="parent-traversal"),
    pytest.param("/Windows", id="root-relative"),
]


@pytest.mark.parametrize("category", ESCAPING_CATEGORIES)
def test_execute_plan_rejects_destination_outside_target(downloads: Path, tmp_path: Path, category: str):
    """Every one of these joins onto `downloads` in a way that lands outside
    it. The file must stay exactly where it was and nothing may appear
    anywhere else on disk."""
    src = make_file(downloads, "photo.jpg", b"private bytes")
    dst = downloads / category / "photo.jpg"

    records = execute_plan(
        [_op(src, dst, category)], execute=True, duplicate_check=True, target=downloads
    )

    assert records[0].status == "rejected_outside_target"
    assert src.exists() and src.read_bytes() == b"private bytes"
    # Nothing escaped: the only thing under the whole tmp tree is the source.
    assert [p.name for p in tmp_path.rglob("*") if p.is_file()] == ["photo.jpg"]
    assert not dst.exists()


def test_execute_plan_rejects_traversal_from_date_routing_format(downloads: Path, tmp_path: Path):
    """The escape need not come from the category: a `date_routing.format`
    of `../../%Y` renders into the subfolder and traverses up out of the
    target just as effectively."""
    outside = tmp_path / "outside"
    outside.mkdir()
    src = make_file(downloads, "report.pdf", b"private bytes")
    dst = downloads / "Documents" / ".." / ".." / "outside" / "report.pdf"

    records = execute_plan(
        [_op(src, dst, "Documents")], execute=True, duplicate_check=True, target=downloads
    )

    assert records[0].status == "rejected_outside_target"
    assert src.exists()
    assert not (outside / "report.pdf").exists()
    assert list(outside.iterdir()) == []


def test_execute_plan_rejects_drive_relative_destination(downloads: Path):
    """`D:evil` keeps its drive letter through the join, so the move would
    land on whatever D:'s current directory happens to be."""
    src = make_file(downloads, "photo.jpg", b"private bytes")

    records = execute_plan(
        [_op(src, downloads / "D:evil" / "photo.jpg", "D:evil")],
        execute=True,
        duplicate_check=True,
        target=downloads,
    )

    assert records[0].status == "rejected_outside_target"
    assert src.exists()


def test_execute_plan_rejects_source_outside_target(downloads: Path, tmp_path: Path):
    """The mirror image: a plan whose *source* is outside the target would
    drag an unrelated file in. `undo_run` checks both ends; so does this."""
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = make_file(outside, "secret.txt", b"sensitive content")

    records = execute_plan(
        [_op(victim, downloads / "Documents" / "secret.txt", "Documents")],
        execute=True,
        duplicate_check=True,
        target=downloads,
    )

    assert records[0].status == "rejected_outside_target"
    assert victim.exists() and victim.read_bytes() == b"sensitive content"
    assert not (downloads / "Documents" / "secret.txt").exists()


def test_dry_run_also_reports_rejection_instead_of_previewing_a_move(downloads: Path):
    """A dry run is what the user decides on. A destination the real run
    would refuse must not preview as an ordinary move."""
    src = make_file(downloads, "photo.jpg")
    dst = downloads / r"C:\Windows\System32" / "photo.jpg"

    records = execute_plan(
        [_op(src, dst, r"C:\Windows\System32")], execute=False, duplicate_check=True, target=downloads
    )

    assert records[0].status == "rejected_outside_target"
    assert src.exists()


def test_execute_plan_does_not_hash_a_file_outside_target(downloads: Path, tmp_path: Path, monkeypatch):
    """Containment is checked before any filesystem access, not just before
    the move: collision resolution alone would stat and SHA-256 whatever sits
    at the destination, which is already a read outside the target."""
    from sorter import mover

    outside = tmp_path / "outside"
    outside.mkdir()
    make_file(outside, "photo.jpg", b"sensitive content")
    src = make_file(downloads, "photo.jpg", b"private bytes")

    def _boom(path, chunk_size=None):  # pragma: no cover - must never run
        raise AssertionError(f"hashed a file outside the target: {path}")

    monkeypatch.setattr(mover, "_sha256", _boom)

    records = execute_plan(
        [_op(src, outside / "photo.jpg", "Images")], execute=True, duplicate_check=True, target=downloads
    )

    assert records[0].status == "rejected_outside_target"
    assert (outside / "photo.jpg").read_bytes() == b"sensitive content"


def test_normal_nested_category_still_moves(downloads: Path):
    """Regression: containment must not reject legitimate nested
    destinations — a category plus a date subfolder is the common case."""
    src = make_file(downloads, "report.pdf", b"contents")
    dst = downloads / "Documents" / "2026" / "09" / "report.pdf"

    records = execute_plan(
        [_op(src, dst, "Documents")], execute=True, duplicate_check=True, target=downloads
    )

    assert records[0].status == "moved"
    assert dst.exists() and dst.read_bytes() == b"contents"
    assert not src.exists()
