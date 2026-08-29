from __future__ import annotations

from pathlib import Path

import pytest

from sorter.config import SorterConfig, load_config


def test_default_config_loads():
    cfg = load_config(None)
    assert "Images" in cfg.categories
    assert ".jpg" in cfg.categories["Images"].extensions


def test_extensions_are_normalized():
    cfg = SorterConfig.model_validate(
        {"categories": {"Images": {"extensions": ["JPG", ".PNG", "gif"]}}}
    )
    assert cfg.categories["Images"].extensions == [".jpg", ".png", ".gif"]


def test_extension_to_category_flattening(default_config: SorterConfig):
    mapping = default_config.extension_to_category()
    assert mapping[".pdf"] == "Documents"
    assert mapping[".mp3"] == "Audio"


def test_missing_config_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "does_not_exist.yaml")


def test_custom_config_from_disk(tmp_path: Path):
    config_path = tmp_path / "custom.yaml"
    config_path.write_text(
        """
categories:
  Notes:
    extensions: [".note"]
fallback_category: null
duplicate_check: false
""",
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.categories["Notes"].extensions == [".note"]
    assert cfg.fallback_category is None
    assert cfg.duplicate_check is False


def test_date_routing_applies_to():
    cfg = SorterConfig.model_validate(
        {"date_routing": {"enabled": True, "categories": ["Documents"]}}
    )
    assert cfg.date_routing.applies_to("Documents") is True
    assert cfg.date_routing.applies_to("Images") is False


def test_date_routing_applies_to_all_when_categories_empty():
    cfg = SorterConfig.model_validate({"date_routing": {"enabled": True, "categories": []}})
    assert cfg.date_routing.applies_to("Anything") is True


def test_date_routing_disabled_by_default():
    cfg = SorterConfig()
    assert cfg.date_routing.applies_to("Documents") is False
