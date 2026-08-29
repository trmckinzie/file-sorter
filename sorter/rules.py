"""Category resolution: extension -> category, with a MIME-type fallback
for extensions the config doesn't know about."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sorter.config import SorterConfig

# Fallback mapping used only when a file's extension isn't listed in any
# configured category. Keyed by the MIME type's major ("type") component,
# with a few specific overrides for common application/* types.
_MIME_MAJOR_TO_CATEGORY = {
    "image": "Images",
    "video": "Videos",
    "audio": "Audio",
    "text": "Documents",
}

_MIME_EXACT_TO_CATEGORY = {
    "application/pdf": "Documents",
    "application/msword": "Documents",
    "application/vnd.ms-excel": "Documents",
    "application/vnd.ms-powerpoint": "Documents",
    "application/zip": "Archives",
    "application/x-tar": "Archives",
    "application/gzip": "Archives",
    "application/x-7z-compressed": "Archives",
    "application/x-rar-compressed": "Archives",
    "application/x-msdownload": "Installers",
    "application/vnd.android.package-archive": "Installers",
    "application/json": "Code",
    "application/javascript": "Code",
}


@dataclass(frozen=True)
class Categorization:
    category: Optional[str]
    """Category name, or None if the file should be left alone (no match
    and no fallback_category configured)."""

    matched_by: str
    """One of "extension", "mime", or "fallback" — useful for preview/debug
    output."""

    subfolder: Optional[str] = None
    """Date-based subfolder (e.g. "2026/08"), if date routing applies."""


class RuleEngine:
    def __init__(self, config: SorterConfig):
        self.config = config
        self._extension_map = config.extension_to_category()

    def categorize(self, path: Path) -> Categorization:
        ext = path.suffix.lower()

        category = self._extension_map.get(ext)
        matched_by = "extension"

        if category is None:
            category = self._categorize_by_mime(path)
            matched_by = "mime"

        if category is None:
            category = self.config.fallback_category
            matched_by = "fallback"

        if category is None:
            return Categorization(category=None, matched_by="none")

        subfolder = self._date_subfolder(path, category)
        return Categorization(category=category, matched_by=matched_by, subfolder=subfolder)

    def _categorize_by_mime(self, path: Path) -> Optional[str]:
        mime_type, _ = mimetypes.guess_type(path.name)
        if mime_type is None:
            return None
        if mime_type in _MIME_EXACT_TO_CATEGORY:
            candidate = _MIME_EXACT_TO_CATEGORY[mime_type]
        else:
            major = mime_type.split("/", 1)[0]
            candidate = _MIME_MAJOR_TO_CATEGORY.get(major)
        # Only honor the guess if that category actually exists in config
        # (or there's no category config at all, e.g. minimal custom configs).
        if candidate and (not self.config.categories or candidate in self.config.categories):
            return candidate
        return None

    def _date_subfolder(self, path: Path, category: str) -> Optional[str]:
        if not self.config.date_routing.applies_to(category):
            return None
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None
        import datetime

        return datetime.datetime.fromtimestamp(mtime).strftime(self.config.date_routing.format)
