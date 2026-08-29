from __future__ import annotations

from pathlib import Path

from sorter.config import SorterConfig
from sorter.mover import build_plan, execute_plan
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
    records = execute_plan(plan, execute=False, duplicate_check=default_config.duplicate_check)

    assert f.exists()
    assert all(r.status == "dry_run" for r in records)


def test_execute_moves_file_into_category_folder(downloads: Path, default_config: SorterConfig):
    f = make_file(downloads, "photo.jpg")
    plan = _plan_for(downloads, default_config)
    records = execute_plan(plan, execute=True, duplicate_check=default_config.duplicate_check)

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
    records = execute_plan(plan, execute=True, duplicate_check=True)

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
    records = execute_plan(plan, execute=True, duplicate_check=True)

    assert records[0].status == "skipped_duplicate"
    # source file is left in place, nothing was deleted
    assert src.exists()


def test_collision_without_duplicate_check_always_renames(downloads: Path, default_config: SorterConfig):
    (downloads / "Images").mkdir()
    make_file(downloads / "Images", "photo.jpg", content=b"same-bytes")
    make_file(downloads, "photo.jpg", content=b"same-bytes")

    plan = _plan_for(downloads, default_config)
    records = execute_plan(plan, execute=True, duplicate_check=False)

    assert records[0].status == "moved"
    assert (downloads / "Images" / "photo (1).jpg").exists()


def test_multiple_collisions_increment_counter(downloads: Path, default_config: SorterConfig):
    (downloads / "Images").mkdir()
    make_file(downloads / "Images", "photo.jpg", content=b"one")
    make_file(downloads / "Images", "photo (1).jpg", content=b"two")
    make_file(downloads, "photo.jpg", content=b"three")

    plan = _plan_for(downloads, default_config)
    records = execute_plan(plan, execute=True, duplicate_check=True)

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
    execute_plan(plan, execute=True, duplicate_check=True)

    year = plan[0].dst.parent.name
    assert (downloads / "Documents" / year / "report.pdf").exists()
