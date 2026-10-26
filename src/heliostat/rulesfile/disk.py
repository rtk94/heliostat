# SPDX-License-Identifier: GPL-2.0-or-later
"""Writing rules.yaml safely: refuse to overwrite outside edits, back up, then replace atomically.

`save(path, data, expected)` compares the file on disk with `expected` (the bytes Heliostat loaded, or
None if there was no file) and raises ExternalChange if they differ, unless `overwrite` is set. Then it
copies the file on disk to `rules.yaml.heliostat-bak.<timestamp>` next to `path`, writes the new data
to a temp file in the directory of the file it replaces, fsyncs it and renames it over the file, and
removes all but the newest BACKUPS_KEPT backups.

A symlinked rules.yaml stays a symlink: the file it points to is replaced (Solaar's own save, a plain
`open(path, "w")`, also writes through the link). Backups go next to `path`, in Solaar's config
directory, not next to the link's target. The file keeps its permission bits; a new file gets 0666
minus the umask, as Solaar's `open` would give it.

The check and the rename are not one atomic step: an outside write in the instant between them is
lost (its content is in no backup either). Solaar writes the file only when its own editor saves.
"""

from __future__ import annotations

import difflib
import os
import re
import secrets
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

BACKUPS_KEPT = 10
BACKUP_INFIX = ".heliostat-bak."
_TIMESTAMP = "%Y%m%dT%H%M%S.%fZ"  # UTC; sorts by name in time order
_TIMESTAMP_RE = r"\d{8}T\d{6}\.\d{6}Z(?:-\d+)?"


class ExternalChange(Exception):
    """The file on disk is not what Heliostat loaded. `expected` / `actual` are None for no file."""

    def __init__(self, path: Path, expected: bytes | None, actual: bytes | None):
        self.path = path
        self.expected = expected
        self.actual = actual
        if actual is None:
            what = "was deleted"
        elif expected is None:
            what = "was created"
        else:
            what = "was changed"
        super().__init__(f"{path} {what} by another program since Heliostat loaded it")

    def diff(self) -> str:
        """Unified diff from the file as loaded to the file on disk now."""
        before = _text(self.expected).splitlines(keepends=True)
        after = _text(self.actual).splitlines(keepends=True)
        lines = difflib.unified_diff(before, after, "as loaded", "on disk now")
        return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def _text(data: bytes | None) -> str:
    return "" if data is None else data.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class SaveResult:
    """What save() did. `written` is False if the file already held exactly `data`."""

    path: Path
    data: bytes
    written: bool
    backup: Path | None = None
    removed_backups: tuple[Path, ...] = ()


def read_bytes(path: Path) -> bytes | None:
    """The file's bytes, or None if it does not exist."""
    try:
        return Path(path).read_bytes()
    except FileNotFoundError:
        return None


def backups(path: Path) -> list[Path]:
    """Heliostat's backups of `path`, oldest first."""
    path = Path(path)
    pattern = re.compile(re.escape(path.name + BACKUP_INFIX) + _TIMESTAMP_RE)
    try:
        names = [entry.name for entry in os.scandir(path.parent) if entry.is_file(follow_symlinks=False)]
    except FileNotFoundError:
        return []
    return [path.parent / name for name in sorted(n for n in names if pattern.fullmatch(n))]


def save(
    path: Path,
    data: bytes | str,
    expected: bytes | None,
    *,
    overwrite: bool = False,
    keep: int = BACKUPS_KEPT,
    now: datetime | None = None,
) -> SaveResult:
    """Write `data` to `path` (see the module docstring). Raises ExternalChange or OSError."""
    path = Path(path)
    if isinstance(data, str):
        data = data.encode("utf-8")
    target = Path(os.path.realpath(path))
    actual = read_bytes(target)
    if actual != expected and not overwrite:
        raise ExternalChange(path, expected, actual)
    if actual == data:
        return SaveResult(path, data, written=False)
    mode = None
    backup = None
    if actual is not None:
        mode = stat.S_IMODE(os.stat(target).st_mode)
        backup = _backup_path(path, now or datetime.now(UTC))
        _write_atomically(backup, actual, mode)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
    _write_atomically(target, data, mode)
    old = backups(path)
    removed = tuple(old[: max(len(old) - keep, 0)])
    for p in removed:
        p.unlink(missing_ok=True)
    return SaveResult(path, data, written=True, backup=backup, removed_backups=removed)


def _backup_path(path: Path, now: datetime) -> Path:
    base = path.parent / f"{path.name}{BACKUP_INFIX}{now.astimezone(UTC).strftime(_TIMESTAMP)}"
    candidate, n = base, 1
    while candidate.exists():
        candidate = base.with_name(f"{base.name}-{n}")
        n += 1
    return candidate


def _write_atomically(target: Path, data: bytes, mode: int | None) -> None:
    """Write a temp file in target's directory, fsync it, rename it over target, fsync the directory."""
    tmp = target.with_name(f".{target.name}.heliostat-tmp-{secrets.token_hex(4)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666 if mode is None else 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            if mode is not None:
                os.fchmod(f.fileno(), mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    dir_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
