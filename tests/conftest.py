from __future__ import annotations

from pathlib import Path

import pytest

from sorter.config import SorterConfig, load_config


@pytest.fixture
def default_config() -> SorterConfig:
    return load_config(None)


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    d = tmp_path / "Downloads"
    d.mkdir()
    return d


def make_file(directory: Path, name: str, content: bytes = b"data") -> Path:
    path = directory / name
    path.write_bytes(content)
    return path
