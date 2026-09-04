"""Target-containment checks shared by every code path that moves a file.

Three modules need to answer the same question — "does this path actually
land inside the directory the user pointed at?" — and they must answer it
identically: `scanner` (is this entry really inside `target`?), `mover` (is
this destination really inside `target`?) and `history` (does this ledger
record really point inside the run's recorded `target`?). A second, subtly
different copy of the check is a silent hole, so there is exactly one here.

This module deliberately imports nothing from `sorter`. `sorter.history`
imports `sorter.mover`, which imports `sorter.scanner`, so anything living in
one of those three is unreachable from the other two without a cycle — which
is why `scanner` previously carried a hand-inlined copy of the predicate.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


class UnsafeDestinationError(ValueError):
    """A configured category or date subfolder cannot be joined onto the
    target directory without risking an escape from it.

    Raised while a plan is being built, so bad config fails loudly and once
    rather than producing a plan whose every entry gets rejected later.
    """


def is_inside(resolved: Path, target_resolved: Path) -> bool:
    """True if an already-resolved path is `target_resolved` or below it.

    Both arguments must already have been through `resolve()`. Comparison is
    on path objects, never strings: `PurePath.__eq__` is case-insensitive on
    Windows, so a `startswith`-style string test would be bypassable by
    casing alone (`c:\\users\\...` vs `C:\\Users\\...`), and `resolve()` has
    already expanded 8.3 short names (`PROGRA~1`), which such a test would
    also miss.
    """
    return resolved == target_resolved or target_resolved in resolved.parents


def escapes_target(path: Path, target_resolved: Path) -> bool:
    """True if `path` does not resolve to somewhere inside `target_resolved`.

    `resolve()` follows symlinks/junctions. That is a deliberate choice, not
    an oversight: containment has to be judged on where a path *actually*
    lands on disk, not on the literal string. Using `absolute()` (which does
    not follow links) would let a path pass this check merely by pointing at
    a symlink planted inside `target` whose real target is outside it —
    exactly the kind of indirection a tampered ledger or a hostile category
    name would use. Resolving is the stricter, safer read of "inside target."

    `resolve()` is non-strict, so a destination that does not exist yet (the
    normal case for a move) resolves fine, with `..` segments collapsed.
    """
    try:
        resolved = path.resolve()
    except OSError:
        # A path component that can't be resolved (e.g. permissions) is
        # treated as escaping — fail closed, not open.
        return True
    return not is_inside(resolved, target_resolved)


def ensure_safe_relative(component: str, kind: str) -> None:
    """Raise `UnsafeDestinationError` unless `component` is a plain relative
    path fragment that can be safely joined onto the target directory.

    This is a purely lexical check on a *configured* value, and it is the
    first of two layers: `escapes_target` still re-checks the real resolved
    destination before anything is moved. It exists because joining is where
    the damage is done and joining is silent — on Windows
    `Path("C:/target") / "C:/Windows/System32"` evaluates to
    `C:/Windows/System32`, discarding the base entirely, and the same is true
    for a UNC share (`\\\\host\\share`), a device path (`\\\\?\\C:\\...`,
    `\\\\.\\...`), a root-relative path (`/Windows`) and a drive-relative one
    on another drive (`D:evil`). Nested names (`Images/2026`) are legitimate
    and stay allowed; `..` segments are not.
    """
    if not component or not component.strip():
        raise UnsafeDestinationError(f"{kind} is empty")

    windows = PureWindowsPath(component)
    posix = PurePosixPath(component)

    # Checked with PureWindowsPath even off Windows so the rule (and the
    # tests asserting it) mean the same thing on every platform: a POSIX
    # `Path` would read "C:\\Windows\\System32" as one odd filename.
    if windows.drive or windows.root or posix.is_absolute():
        raise UnsafeDestinationError(
            f"{kind} {component!r} is an absolute, UNC, device or drive-relative path. "
            "It must be a plain relative folder name, otherwise joining it onto the "
            "target directory silently discards the target and moves files elsewhere."
        )

    if ".." in windows.parts or ".." in posix.parts:
        raise UnsafeDestinationError(
            f"{kind} {component!r} contains a '..' segment, which would traverse "
            "up out of the target directory."
        )
