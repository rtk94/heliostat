# SPDX-License-Identifier: GPL-2.0-or-later
"""The generated Solaar name tables, and lookups that mirror Solaar's NamedInts and Feature."""

import subprocess
import sys
from pathlib import Path

import pytest

from heliostat.analysis.solaar_model import exact_tag, names, tag_for_version

ROOT = Path(__file__).resolve().parents[1]


def test_names_module_is_up_to_date():
    if not all((ROOT / ".solaar" / tag / "lib").is_dir() for tag in ("1.1.14", "1.1.20")):
        pytest.skip("Solaar checkouts missing; run tools/fetch_solaar.sh")
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_solaar_names.py"), "--check"], capture_output=True)
    assert done.returncode == 0, done.stderr.decode()


def test_names_module_keeps_solaar_copyright_notices():
    from heliostat.solaar import names as module

    doc = module.__doc__
    assert "Derived from Solaar" in doc
    for line in (
        "Copyright (C) 2012-2013  Daniel Pavel",
        "Copyright (C) 2014-2024  Solaar Contributors https://pwr-solaar.github.io/Solaar/",
        "Copyright (C) 2020 Peter Patel-Schneider",
    ):
        assert line in doc


@pytest.mark.parametrize("tag", ["1.1.14", "1.1.20"])
def test_key_lookup(tag):
    n = names(tag)
    assert n.key_control("Back Button") == n.key_control("Back_Button") == 0x53
    assert n.key_control("back button") is None  # passes `in CONTROL`, then CONTROL[name] is None
    assert n.key_control("unknown:0053") == 0x53
    assert n.key_control("unknown:1234") == 0x1234
    assert n.key_control("G7") == 0x1007 and n.key_control("MR") == 0x1200
    assert n.key_control(5) is None
    with pytest.raises(ValueError):
        n.key_control("unknown:zz")
    assert n.key_is_down_control("unknown:0053") is None  # KeyIsDown has no unknown: lookup
    assert n.control_name(0x53) == "Back Button" and n.control_name(0xFFFF) == "unknown:FFFF"


@pytest.mark.parametrize("tag", ["1.1.14", "1.1.20"])
def test_mouse_gesture_names_are_exact(tag):
    n = names(tag)
    assert n.control_by_name("Back Button") == 0x53
    assert n.control_by_name("Back_Button") is None
    assert n.control_by_name("unknown:FFFF") == 0xFFFF
    assert n.control_by_name("unknown:0053") is None  # Solaar prints 0x53 as Back Button
    assert n.is_movement("Mouse Up-left") and not n.is_movement("Mouse up")


def test_renames_between_tags():
    old, new = names("1.1.14"), names("1.1.20")
    assert old.control_name(old.key_control("Voice Dictation")) == "Voice Dictation"
    assert new.key_control("Voice Dictation") is None
    assert new.control_name(old.key_control("Voice Dictation")) == "Dictation"
    # Same name, different control: 1.1.15 gave the Fn keys the plain names.
    assert old.key_control("Play/Pause") == 0x04 and new.key_control("Play/Pause") == old.key_control("Play/Pause Fn")


def test_feature_lookup():
    assert names("1.1.14").feature("THUMB_WHEEL") == names("1.1.20").feature("THUMB_WHEEL") == 0x2150
    assert names("1.1.14").feature("THUMB WHEEL") is None
    assert names("1.1.20").feature("THUMB WHEEL") == 0x2150
    assert names("1.1.14").feature("None") is None


def test_version_to_tag():
    assert tag_for_version((1, 1, 14)) == "1.1.14" and exact_tag((1, 1, 14))
    assert tag_for_version((1, 1, 13)) == "1.1.14" and not exact_tag((1, 1, 13))
    assert tag_for_version((1, 1, 15)) == "1.1.20" and not exact_tag((1, 1, 15))
    assert tag_for_version((1, 1, 20)) == "1.1.20" and exact_tag((1, 1, 20))
    assert tag_for_version((1, 2, 0)) == "1.1.20" and not exact_tag((1, 2, 0))
