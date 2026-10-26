# SPDX-License-Identifier: GPL-2.0-or-later
"""rulesfile.save: external-change refusal, backups and their rotation, atomic replace. Temp dirs only."""

import os
import stat
from datetime import UTC, datetime, timedelta

import pytest

from heliostat.rulesfile import BACKUPS_KEPT, ExternalChange, backups, disk, read_bytes, save

OLD = b"%YAML 1.3\n---\n- Key: [Back Button, pressed]\n- KeyPress: a\n...\n"
NEW = b"%YAML 1.3\n---\n- Key: [Back Button, pressed]\n- KeyPress: b\n...\n"

T0 = datetime(2026, 10, 26, 7, 0, 0, tzinfo=UTC)


@pytest.fixture
def rules(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_bytes(OLD)
    path.chmod(0o640)
    return path


def _leftovers(directory):
    return [p.name for p in directory.iterdir() if "heliostat-tmp" in p.name]


def test_save_writes_and_backs_up(rules):
    result = save(rules, NEW, OLD, now=T0)
    assert rules.read_bytes() == NEW
    assert result.written and result.data == NEW
    assert result.backup == rules.with_name("rules.yaml.heliostat-bak.20261026T070000.000000Z")
    assert result.backup.read_bytes() == OLD
    assert backups(rules) == [result.backup]
    assert stat.S_IMODE(rules.stat().st_mode) == 0o640
    assert stat.S_IMODE(result.backup.stat().st_mode) == 0o640
    assert _leftovers(rules.parent) == []


def test_save_accepts_text(rules):
    save(rules, NEW.decode(), OLD, now=T0)
    assert rules.read_bytes() == NEW


def test_save_creates_a_missing_file_without_backup(tmp_path):
    path = tmp_path / "solaar" / "rules.yaml"
    result = save(path, NEW, None)
    assert path.read_bytes() == NEW
    assert result.backup is None and backups(path) == []
    umask = os.umask(0)
    os.umask(umask)
    assert stat.S_IMODE(path.stat().st_mode) == 0o666 & ~umask


def test_unchanged_data_writes_nothing(rules):
    before = rules.stat().st_mtime_ns
    result = save(rules, OLD, OLD)
    assert not result.written and result.backup is None
    assert backups(rules) == []
    assert rules.stat().st_mtime_ns == before


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda p: p.write_bytes(OLD + b"---\n- Process: kwin\n...\n"), "was changed"),
        (lambda p: p.unlink(), "was deleted"),
    ],
)
def test_external_change_is_refused(rules, change, message):
    change(rules)
    on_disk = read_bytes(rules)
    with pytest.raises(ExternalChange, match=message) as info:
        save(rules, NEW, OLD)
    assert read_bytes(rules) == on_disk
    assert backups(rules) == []
    assert info.value.expected == OLD and info.value.actual == on_disk


def test_external_change_diff(rules):
    rules.write_bytes(OLD.replace(b"KeyPress: a", b"KeyPress: c"))
    with pytest.raises(ExternalChange) as info:
        save(rules, NEW, OLD)
    diff = info.value.diff()
    assert "--- as loaded\n+++ on disk now\n" in diff
    assert "-- KeyPress: a\n+- KeyPress: c\n" in diff


def test_created_externally_is_refused(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_bytes(OLD)
    with pytest.raises(ExternalChange, match="was created"):
        save(path, NEW, None)


def test_overwrite_backs_up_the_external_version(rules):
    external = OLD + b"---\n- Process: kwin\n...\n"
    rules.write_bytes(external)
    result = save(rules, NEW, OLD, overwrite=True, now=T0)
    assert rules.read_bytes() == NEW
    assert result.backup.read_bytes() == external


def test_backups_rotate_at_ten(rules):
    unrelated = ["rules.yaml.heliostat-bak.old", "rules.yaml.bak", "other.yaml.heliostat-bak.20200101T000000.000000Z"]
    for name in unrelated:
        (rules.parent / name).write_text("keep me")
    expected = OLD
    made = []
    for i in range(BACKUPS_KEPT + 3):
        data = NEW + f"# {i}\n".encode()
        result = save(rules, data, expected, now=T0 + timedelta(seconds=i))
        made.append(result.backup)
        expected = data
    kept = backups(rules)
    assert len(kept) == BACKUPS_KEPT
    assert kept == made[-BACKUPS_KEPT:]
    assert not any(p.exists() for p in made[:3])
    assert made[0].name.endswith("T070000.000000Z")
    assert kept[-1].read_bytes() == NEW + b"# 11\n"
    for name in unrelated:
        assert (rules.parent / name).read_text() == "keep me"


def test_backup_names_do_not_collide(rules):
    first = save(rules, NEW, OLD, now=T0)
    second = save(rules, OLD, NEW, now=T0)
    assert first.backup != second.backup
    assert second.backup.name.endswith("Z-1")
    assert backups(rules) == [first.backup, second.backup]


def test_symlink_is_kept(tmp_path):
    real_dir = tmp_path / "dotfiles"
    real_dir.mkdir()
    real = real_dir / "rules.yaml"
    real.write_bytes(OLD)
    config = tmp_path / "config"
    config.mkdir()
    link = config / "rules.yaml"
    link.symlink_to(real)
    result = save(link, NEW, OLD, now=T0)
    assert link.is_symlink() and real.read_bytes() == NEW
    assert result.backup.parent == config  # backups next to the path Solaar uses
    assert _leftovers(real_dir) == [] and _leftovers(config) == []


def test_failed_write_leaves_the_file_alone(rules, monkeypatch):
    real_replace = os.replace

    def failing_replace(src, dst):
        if os.fspath(dst) == os.fspath(rules):
            raise OSError(28, "No space left on device")
        real_replace(src, dst)

    monkeypatch.setattr(disk.os, "replace", failing_replace)
    with pytest.raises(OSError, match="No space"):
        save(rules, NEW, OLD, now=T0)
    assert rules.read_bytes() == OLD
    assert _leftovers(rules.parent) == []
