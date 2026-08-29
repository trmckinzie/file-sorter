from __future__ import annotations

from pathlib import Path

from sorter.config import SorterConfig
from sorter.rules import RuleEngine
from tests.conftest import make_file


def test_categorize_by_extension(downloads: Path, default_config: SorterConfig):
    engine = RuleEngine(default_config)
    f = make_file(downloads, "photo.jpg")
    result = engine.categorize(f)
    assert result.category == "Images"
    assert result.matched_by == "extension"


def test_categorize_falls_back_to_mime_when_extension_unknown():
    cfg = SorterConfig.model_validate(
        {"categories": {"Images": {"extensions": []}}, "fallback_category": None}
    )
    engine = RuleEngine(cfg)
    result = engine.categorize(Path("picture.png"))
    assert result.category == "Images"
    assert result.matched_by == "mime"


def test_categorize_uses_fallback_category(downloads: Path):
    cfg = SorterConfig.model_validate({"categories": {}, "fallback_category": "Other"})
    engine = RuleEngine(cfg)
    f = make_file(downloads, "mystery.xyz123")
    result = engine.categorize(f)
    assert result.category == "Other"
    assert result.matched_by == "fallback"


def test_categorize_returns_none_without_fallback():
    cfg = SorterConfig.model_validate({"categories": {}, "fallback_category": None})
    engine = RuleEngine(cfg)
    result = engine.categorize(Path("mystery.xyz123"))
    assert result.category is None


def test_extension_match_takes_priority_over_mime():
    # .txt would normally MIME-sniff to "text/plain" -> Documents, but here
    # we deliberately map it to a different category via config.
    cfg = SorterConfig.model_validate({"categories": {"Notes": {"extensions": [".txt"]}}})
    engine = RuleEngine(cfg)
    result = engine.categorize(Path("todo.txt"))
    assert result.category == "Notes"
    assert result.matched_by == "extension"


def test_date_subfolder_included_when_enabled(downloads: Path):
    cfg = SorterConfig.model_validate(
        {
            "categories": {"Documents": {"extensions": [".pdf"]}},
            "date_routing": {"enabled": True, "format": "%Y"},
        }
    )
    engine = RuleEngine(cfg)
    f = make_file(downloads, "report.pdf")
    result = engine.categorize(f)
    assert result.category == "Documents"
    assert result.subfolder is not None
    assert len(result.subfolder) == 4  # a 4-digit year


def test_no_subfolder_when_date_routing_disabled(downloads: Path, default_config: SorterConfig):
    engine = RuleEngine(default_config)
    f = make_file(downloads, "report.pdf")
    result = engine.categorize(f)
    assert result.subfolder is None
