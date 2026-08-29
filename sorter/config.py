"""Configuration schema and loading for file-sorter.

Config is authored as YAML and validated into pydantic models so that
malformed user config fails fast with a clear error instead of surfacing
as a confusing exception deep in the scanning/moving pipeline.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator

DEFAULT_CONFIG_RESOURCE = "default_config.yaml"


class CategoryRule(BaseModel):
    """Maps a category name to the file extensions that belong in it."""

    extensions: list[str] = Field(default_factory=list)

    @field_validator("extensions")
    @classmethod
    def _normalize_extensions(cls, value: list[str]) -> list[str]:
        normalized = []
        for ext in value:
            ext = ext.lower().strip()
            if not ext.startswith("."):
                ext = f".{ext}"
            normalized.append(ext)
        return normalized


class IgnoreConfig(BaseModel):
    extensions: list[str] = Field(default_factory=list)
    filenames: list[str] = Field(default_factory=list)
    hidden: bool = True

    @field_validator("extensions")
    @classmethod
    def _normalize_extensions(cls, value: list[str]) -> list[str]:
        normalized = []
        for ext in value:
            ext = ext.lower().strip()
            if not ext.startswith("."):
                ext = f".{ext}"
            normalized.append(ext)
        return normalized


class DateRoutingConfig(BaseModel):
    enabled: bool = False
    format: str = "%Y/%m"
    categories: list[str] = Field(default_factory=list)

    def applies_to(self, category: str) -> bool:
        if not self.enabled:
            return False
        if not self.categories:
            return True
        return category in self.categories


class SorterConfig(BaseModel):
    categories: dict[str, CategoryRule] = Field(default_factory=dict)
    fallback_category: Optional[str] = "Other"
    ignore: IgnoreConfig = Field(default_factory=IgnoreConfig)
    date_routing: DateRoutingConfig = Field(default_factory=DateRoutingConfig)
    duplicate_check: bool = True

    def extension_to_category(self) -> dict[str, str]:
        """Flatten category -> extensions into extension -> category."""
        mapping: dict[str, str] = {}
        for category, rule in self.categories.items():
            for ext in rule.extensions:
                mapping[ext] = category
        return mapping


def load_default_config_text() -> str:
    return resources.files("sorter").joinpath(DEFAULT_CONFIG_RESOURCE).read_text(encoding="utf-8")


def load_config(path: Optional[Path] = None) -> SorterConfig:
    """Load and validate config from `path`, falling back to the bundled default."""
    if path is None:
        raw = yaml.safe_load(load_default_config_text())
    else:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw = raw or {}
    return SorterConfig.model_validate(raw)
