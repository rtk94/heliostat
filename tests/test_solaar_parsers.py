# SPDX-License-Identifier: GPL-2.0-or-later
"""Parsers for `solaar` CLI output, against every captured fixture and against altered copies of them."""

import re
from pathlib import Path

import pytest

from heliostat.solaar import Device, DivertMode, SolaarOutputError
from heliostat.solaar.parsers import (
    controls_from_show,
    parse_config,
    parse_config_setting,
    parse_divert_keys,
    parse_divert_map,
    parse_set_divert,
    parse_show,
    parse_version,
)

FIXTURES = Path(__file__).parent / "fixtures" / "solaar"
ALL_FILES = sorted(p for p in FIXTURES.glob("*/*") if p.name != "README.md")
V1114 = FIXTURES / "1.1.14"


def _parse_fixture(path: Path):
    text = path.read_text()
    name = path.name
    if name == "version.txt":
        return parse_version(text)
    if name.startswith("show_"):
        show = parse_show(text)
        return show, [controls_from_show(e, text) for e in show.devices]
    if name.startswith("config_"):
        return parse_config(text)
    if name.startswith("divert_keys_"):
        return parse_divert_keys(text)
    if name.startswith("set_"):
        return parse_set_divert(text)
    raise AssertionError(f"no parser for fixture {path}; name it after the command it captures")


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_fixture_parses(path):
    assert _parse_fixture(path)


@pytest.mark.parametrize("version_dir", sorted(p for p in FIXTURES.iterdir() if p.is_dir()), ids=lambda p: p.name)
def test_fixture_versions_match_their_directory(version_dir):
    assert ".".join(map(str, parse_version((version_dir / "version.txt").read_text()))) == version_dir.name
    assert parse_show((version_dir / "show_all.txt").read_text()).version.startswith(version_dir.name)


# ---------------------------------------------------------------------------------------- 1.1.14 values


def test_version():
    assert parse_version("solaar 1.1.14-4\n") == (1, 1, 14)
    assert parse_version("solaar 1.1.20\n") == (1, 1, 20)
    with pytest.raises(SolaarOutputError):
        parse_version("Solaar version 1.1.14\n")


def test_show_devices():
    show = parse_show((V1114 / "show_all.txt").read_text())
    assert show.version == "1.1.14-4"
    assert [e.device for e in show.devices] == [
        Device("MX MCHNCL", "MX MCHNCL", "AAAA0001", None, "keyboard", False),
        Device("Logi M650", "Logi M650", "AAAA0002", None, "mouse", False),
        Device("MX Mechanical", "MX MCHNCL", "AAAA0001", "AAAA0001", "keyboard", True),
        Device("Signature M650 Mouse", "Logi M650", "AAAA0002", "AAAA0002", "mouse", True),
    ]
    receivers = [e.receiver_serial for e in show.devices]
    assert receivers == ["00000000000000000000000000000001"] * 2 + ["00000000000000000000000000000002"] * 2
    assert [e.wpid for e in show.devices] == ["B366", "B02A", "B366", "B02A"]
    assert [len(e.features) for e in show.devices] == [0, 0, 33, 30]
    assert [None if e.keys is None else len(e.keys) for e in show.devices] == [None, None, 41, 6]


def test_show_controls_mouse():
    show = parse_show(text := (V1114 / "show_all.txt").read_text())
    controls = {c.name: c for c in controls_from_show(show.devices[3], text)}
    assert list(controls) == [
        "Left Button",
        "Right Button",
        "Middle Button",
        "Back Button",
        "Forward Button",
        "Virtual Gesture Button",
    ]
    all_modes = (DivertMode.REGULAR, DivertMode.DIVERTED, DivertMode.MOUSE_GESTURES, DivertMode.SLIDING_DPI)
    for name in ("Middle Button", "Back Button", "Forward Button"):
        c = controls[name]
        assert (c.divertable, c.mode, c.saved_mode) == (True, DivertMode.REGULAR, DivertMode.REGULAR)
        assert c.modes == all_modes
    for name in ("Left Button", "Right Button", "Virtual Gesture Button"):  # virtual: not in divert-keys
        assert (controls[name].divertable, controls[name].mode, controls[name].modes) == (False, None, ())
    assert controls["Back Button"].flags == (
        "mse",
        "reprogrammable",
        "divertable",
        "raw xy",
        "analytics key events",
        "unknown:000800",
    )


def test_show_controls_keyboard():
    show = parse_show(text := (V1114 / "show_all.txt").read_text())
    controls = controls_from_show(show.devices[2], text)
    divertable = [c for c in controls if c.divertable]
    assert len(controls) == 41 and len(divertable) == 36
    assert {c.modes for c in divertable} == {(DivertMode.REGULAR, DivertMode.DIVERTED)}
    assert {c.mode for c in divertable} == {DivertMode.REGULAR}
    assert [c.name for c in controls if not c.divertable] == [
        "Host Switch Channel 1",
        "Host Switch Channel 2",
        "Host Switch Channel 3",
        "F Lock",
        "FN Key",
    ]


def test_show_offline_devices_have_no_controls():
    show = parse_show(text := (V1114 / "show_all.txt").read_text())
    assert controls_from_show(show.devices[0], text) == []


def test_config_keyboard():
    config = parse_config((V1114 / "config_mx-mechanical.txt").read_text())
    assert (config.name, config.codename, config.wpid, config.serial) == (
        "MX Mechanical",
        "MX MCHNCL",
        "B366",
        "AAAA0001",
    )
    assert [s.name for s in config.settings] == [
        "backlight",
        "fn-swap",
        "divert-keys",
        "disable-keyboard-keys",
        "multiplatform",
        "change-host",
    ]
    backlight = config.setting("backlight")
    assert backlight.label == "Backlight"
    assert backlight.description == "Illumination level on keyboard.  Changes made are only applied in Manual mode."
    assert backlight.possible_values == "one of [ Enabled, Disabled ], or higher/lower/highest/max/lowest/min"
    assert backlight.value == "Disabled"
    divert = config.setting("divert-keys")
    assert divert.possible_values is None
    assert len(parse_divert_map(divert.value)) == 36


def test_config_mouse():
    config = parse_config((V1114 / "config_signature-m650.txt").read_text())
    assert (config.name, config.codename, config.wpid, config.serial) == (
        "Signature M650 Mouse",
        "Logi M650",
        "B02A",
        "AAAA0002",
    )
    assert config.setting("dpi").value == "1000"
    assert config.setting("lowres-scroll-mode").label == "Scroll Wheel Diversion"
    assert config.setting("reprogrammable-keys").value.startswith("{Middle Button:Mouse Middle Button,")


def test_divert_keys_files():
    regular = parse_divert_keys((V1114 / "divert_keys_signature-m650.txt").read_text())
    assert regular == {n: DivertMode.REGULAR for n in ("Middle Button", "Back Button", "Forward Button")}
    diverted = parse_divert_keys((V1114 / "divert_keys_signature-m650_back-diverted.txt").read_text())
    gestures = parse_divert_keys((V1114 / "divert_keys_signature-m650_back-gestures.txt").read_text())
    # The CLI reads only the divert bit: Mouse Gestures reads back as Diverted.
    assert diverted == gestures == {**regular, "Back Button": DivertMode.DIVERTED}
    assert len(parse_divert_keys((V1114 / "divert_keys_mx-mechanical.txt").read_text())) == 36


def test_divert_keys_agree_with_show_and_config():
    show_text = (V1114 / "show_all.txt").read_text()
    for entry, short in zip(parse_show(show_text).devices[2:], ("mx-mechanical", "signature-m650"), strict=True):
        from_show = parse_divert_map(entry.diversion)
        assert from_show == parse_divert_map(entry.diversion_saved)
        assert from_show == parse_divert_keys((V1114 / f"divert_keys_{short}.txt").read_text())
        config = parse_config((V1114 / f"config_{short}.txt").read_text())
        assert from_show == parse_divert_map(config.setting("divert-keys").value)


def test_set_divert_output():
    text = (V1114 / "set_mouse_gestures_signature-m650_back.txt").read_text()
    assert parse_set_divert(text) == ("Signature M650 Mouse", "Back Button", DivertMode.MOUSE_GESTURES)


# ---------------------------------------------------------------------------------- gesture-mode handling


def _back_button(text):
    controls = controls_from_show(parse_show(text).devices[3], text)
    return next(c for c in controls if c.name == "Back Button")


def test_back_button_in_mouse_gestures_mode():
    """M650 Back Button set to Mouse Gestures: the device reads Diverted, Solaar's config.yaml says Mouse Gestures."""
    text = (V1114 / "show_all_back-gestures.txt").read_text()
    mouse = parse_show(text).devices[3]
    assert mouse.device.name == "Signature M650 Mouse"
    assert parse_divert_map(mouse.diversion)["Back Button"] is DivertMode.DIVERTED
    assert parse_divert_map(mouse.diversion_saved)["Back Button"] is DivertMode.MOUSE_GESTURES
    back = _back_button(text)
    assert back.mode is DivertMode.DIVERTED_MODE_UNKNOWN
    assert back.mode.value == "diverted (gesture mode unknown)" and back.mode.diverted
    assert back.saved_mode is DivertMode.MOUSE_GESTURES
    others = [c for c in controls_from_show(mouse, text) if c.divertable and c.name != "Back Button"]
    assert [(c.name, c.mode, c.saved_mode) for c in others] == [
        ("Middle Button", DivertMode.REGULAR, DivertMode.REGULAR),
        ("Forward Button", DivertMode.REGULAR, DivertMode.REGULAR),
    ]


def test_diverted_plain_control_is_diverted():
    text = (V1114 / "show_all.txt").read_text()
    text = text.replace("Diversion        : {Calculator:Regular,", "Diversion        : {Calculator:Diverted,")
    controls = controls_from_show(parse_show(text).devices[2], text)
    assert next(c for c in controls if c.name == "Calculator").mode is DivertMode.DIVERTED


def test_unreadable_live_diversion_leaves_mode_unknown():
    text = (V1114 / "show_all.txt").read_text()
    text = re.sub(r"(Key/Button Diversion        : )\{Middle Button.*", r"\1HID++ error {'number': 2}", text)
    back = _back_button(text)
    assert back.divertable and back.mode is None and back.saved_mode is DivertMode.REGULAR


# --------------------------------------------------------------------------------------- loud failures


def _mutated(old, new, count=1):
    text = (V1114 / "show_all.txt").read_text()
    assert text.count(old) >= count
    return text.replace(old, new, count)


@pytest.mark.parametrize(
    "old, new",
    [
        ("solaar version 1.1.14-4", "Solaar 1.1.14-4"),
        ("     Kind         : mouse\n     Protocol     : HID++ 4.5", "     Kind         : mouse\n     Colour: blue"),
        ("     Protocol     : unknown (device is offline)\n", ""),
        ("     Protocol     : HID++ 4.5", "     Protocol     : HID++ ???"),
        ("     Has 6 reprogrammable keys:", "     Has 7 reprogrammable keys:"),
        ("     Supports 30 HID++ 2.0 features:", "     Supports 31 HID++ 2.0 features:"),
        ("  Has 2 paired device(s) out of a maximum of 6.", "  Has two paired devices."),
        ("             reporting: default\n     Battery: 50%", "        ??\n     Battery: 50%"),
        ("Diversion        : {Middle Button:Regular, Back", "Diversion        : {Middle Button:Sideways, Back"),
        ("Forward Button:Regular}\n         9", "Forward Button:Regular, Left Button:Regular}\n         9"),
        ("divertable, virtual, raw XY", "divertable, raw XY"),
        ("  2: Signature M650 Mouse", "\nSignature M650 Mouse\nx"),
    ],
)
def test_unrecognized_show_output_raises_with_raw_text(old, new):
    text = _mutated(old, new)
    with pytest.raises(SolaarOutputError) as info:
        show = parse_show(text)
        for entry in show.devices:
            controls_from_show(entry, text)
    assert info.value.raw == text
    assert "--- raw output ---" in str(info.value)


def test_missing_flags_line_raises():
    text = _mutated(
        "             mse, analytics key events, pos:0, group:1, group mask:empty\n             reporting: default\n",
        "",
    )
    with pytest.raises(SolaarOutputError, match="no flags line"):
        parse_show(text)


@pytest.mark.parametrize(
    "value",
    [
        "Middle Button:Regular",
        "{Middle Button:Regular, Back Button:Maybe}",
        "{Middle Button:Regular, ?}",
        "{Middle Button:Regular, Middle Button:Diverted}",
        "{Middle Button:Regular,Back Button:Regular}",
    ],
)
def test_bad_divert_maps_raise(value):
    with pytest.raises(SolaarOutputError):
        parse_divert_map(value)


def test_divert_map_handles_awkward_names():
    assert parse_divert_map("{}") == {}
    assert parse_divert_map("{unknown:00A1:Diverted, Left Option/Start:Regular}") == {
        "unknown:00A1": DivertMode.DIVERTED,
        "Left Option/Start": DivertMode.REGULAR,
    }


@pytest.mark.parametrize(
    "text",
    [
        "MX Mechanical [B366:AAAA0001]\n\n# Backlight\nbacklight = Disabled\n",
        "MX Mechanical (MX MCHNCL) [B366:AAAA0001]\n\n# Backlight\nbacklight: Disabled\n",
        "MX Mechanical (MX MCHNCL) [B366:AAAA0001]\n\nbacklight = Disabled\n",
        "MX Mechanical (MX MCHNCL) [B366:AAAA0001]\n\n# A\n# B\n# C\n# D\nbacklight = Disabled\n",
        "MX Mechanical (MX MCHNCL) [B366:AAAA0001]\n",
        "MX Mechanical (MX MCHNCL) [B366:AAAA0001]\n\n# A\na = 1\n\n# A\na = 2\n",
    ],
)
def test_bad_config_raises(text):
    with pytest.raises(SolaarOutputError):
        parse_config(text)


def test_config_read_failure_is_none():
    config = parse_config("D (C) [B366:1]\n\n# Backlight\nbacklight = ? (failed to read from device)\n")
    assert config.setting("backlight").value is None
    with pytest.raises(SolaarOutputError, match="failed to read"):
        parse_divert_keys("# Key/Button Diversion\n# Make the key\ndivert-keys = ? (failed to read from device)\n")


def test_divert_keys_expects_the_divert_setting():
    with pytest.raises(SolaarOutputError):
        parse_config_setting("# Backlight\nbacklight = Disabled\n", "divert-keys")
    with pytest.raises(SolaarOutputError):
        parse_divert_keys("# Tastenumleitung\n# x\ndivert-keys = {Back Button:Regular}\n")


@pytest.mark.parametrize(
    "text",
    [
        "Setting divert-keys of Signature M650 Mouse key Back Button to Mouse Gestures\n",
        "Setting divert-keys of M key NamedInt(83, 'Back Button') to NamedInt(9, 'Sideways')\n",
        "",
    ],
)
def test_bad_set_output_raises(text):
    with pytest.raises(SolaarOutputError):
        parse_set_divert(text)


# ------------------------------------------------------------------------------------- 1.1.20 vs 1.1.14

V1120 = FIXTURES / "1.1.20"

# Control names 1.1.15 changed (special_keys.CONTROL), as seen on the MX Mechanical. Same control, same index.
RENAMED_1_1_15 = {
    "Voice Dictation": "Dictation",
    "Open Emoji Panel": "Emoji",
    "Snipping Tool": "Screen Capture",
    "Previous Fn": "Previous Track",
    "Play/Pause Fn": "Play/Pause",
    "Next Fn": "Next Track",
    "Mute Fn": "Mute Sound",
    "Volume Down Fn": "Volume Down",
    "Volume Up Fn": "Volume Up",
    "Lock PC": "Screen Lock",
}


def _renamed(name):
    return RENAMED_1_1_15.get(name, name)


def _both_shows():
    texts = [(V / "show_all.txt").read_text() for V in (V1114, V1120)]
    return [(parse_show(t), t) for t in texts]


def test_1_1_20_devices():
    (old, _), (new, _) = _both_shows()
    assert new.version == "1.1.20"
    assert len(old.devices) == len(new.devices) == 4
    for a, b in zip(old.devices, new.devices, strict=True):
        assert (a.device.name, a.device.online) == (b.device.name, b.device.online)
        assert a.receiver_serial == b.receiver_serial
        if a.device.online:
            assert a.device == b.device
            assert a.features.keys() == b.features.keys()  # after undoing 1.1.20's byte-swapped unknown IDs
        else:
            # 1.1.20 prints only "N: name" and "Device is offline." for an offline pairing.
            assert b.device == Device(a.device.name, None, None, None, None, False)
            assert b.wpid is None and b.keys is None


def test_1_1_20_controls():
    (old, old_text), (new, new_text) = _both_shows()
    for a, b in zip(old.devices[2:], new.devices[2:], strict=True):
        old_controls = controls_from_show(a, old_text)
        new_controls = controls_from_show(b, new_text)
        assert [_renamed(c.name) for c in old_controls] == [c.name for c in new_controls]
        old_divertable = {_renamed(c.name) for c in old_controls if c.divertable}
        assert old_divertable == {c.name for c in new_controls if c.divertable}
        for oc, nc in zip(old_controls, new_controls, strict=True):
            assert (oc.divertable, oc.modes) == (nc.divertable, nc.modes)
            assert (oc.mode, oc.saved_mode) == (nc.mode, nc.saved_mode)
            # Same flags once spelled alike; 1.1.14 has no name for bit 0x800, 1.1.20 calls it raw_wheel.
            old_flags = {"raw wheel" if f == "unknown:000800" else f for f in oc.flags}
            assert old_flags == set(nc.flags)
    renamed_keys = [k.name for k in old.devices[2].keys if k.name in RENAMED_1_1_15]
    assert sorted(renamed_keys) == sorted(RENAMED_1_1_15)


@pytest.mark.parametrize("short", ["mx-mechanical", "signature-m650"])
def test_1_1_20_config_and_divert_keys(short):
    old = parse_config((V1114 / f"config_{short}.txt").read_text())
    new = parse_config((V1120 / f"config_{short}.txt").read_text())
    assert (old.name, old.codename, old.wpid, old.serial) == (new.name, new.codename, new.wpid, new.serial)
    assert [s.name for s in old.settings] == [s.name for s in new.settings]
    assert [s.label for s in old.settings] == [s.label for s in new.settings]
    old_divert = parse_divert_keys((V1114 / f"divert_keys_{short}.txt").read_text())
    new_divert = parse_divert_keys((V1120 / f"divert_keys_{short}.txt").read_text())
    assert {_renamed(k): v for k, v in old_divert.items()} == new_divert
    assert new_divert == parse_divert_map(new.setting("divert-keys").value)


def test_unknown_feature_ids_are_taken_from_the_name():
    (old, _), (new, _) = _both_shows()
    for show in (old, new):
        keyboard = show.devices[2]
        assert keyboard.features[0x1803] == "unknown:1803"
        assert 0x0318 not in keyboard.features
    text = (V1120 / "show_all.txt").read_text()
    text = text.replace("unknown:1803           {0318}", "unknown:1803           {1234}", 1)
    with pytest.raises(SolaarOutputError, match="printed as"):
        parse_show(text)
