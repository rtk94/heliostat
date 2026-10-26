# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure parsers for `solaar` CLI output.

Formats come from lib/solaar/cli/show.py and config.py in the pinned checkouts; the captured output
under tests/fixtures/solaar/<version>/ is the ground truth. Anything a parser does not recognize
raises SolaarOutputError with the raw text attached. Text in the output that Solaar translates
(setting labels, mode names) is parsed in its untranslated form, so the CLI must run with LANGUAGE=C.

Version notes (confirmed by the 1.1.14 and 1.1.20 fixtures):
- 1.1.14 prints key flags as "raw XY", "analytics key events"; 1.1.20 as "raw_xy", "analytics_key_events".
  Flags are normalized to lower case with spaces.
- 1.1.14 prints an offline device's full header with "Protocol : unknown (device is offline)";
  1.1.20 prints only the "N: name" line and "Device is offline.", so its codename, serial and kind are None.
- 1.1.20 prints the IDs of unnamed features ("unknown:1803") byte-swapped; see _feature_id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from heliostat.solaar.client import SETTABLE_MODES, Control, Device, DivertMode, SolaarOutputError

ADJUSTABLE_DPI = 0x2201  # HID++ feature that makes Solaar offer Sliding DPI on raw-XY controls
DIVERSION_LABEL = "Key/Button Diversion"  # DivertKeys.label
DIVERT_SETTING = "divert-keys"


# ---------------------------------------------------------------------------------------------- version


_VERSION_RE = re.compile(r"solaar (\d+)\.(\d+)\.(\d+)(\S*)")


def parse_version(text: str) -> tuple[int, int, int]:
    """`solaar --version`, e.g. "solaar 1.1.14-4"."""
    lines = [line for line in text.splitlines() if line.strip()]
    m = _VERSION_RE.fullmatch(lines[0].strip()) if len(lines) == 1 else None
    if not m:
        raise SolaarOutputError("expected one line 'solaar X.Y.Z'", text)
    return int(m[1]), int(m[2]), int(m[3])


# ------------------------------------------------------------------------------------------------- show


@dataclass(frozen=True)
class ShowKey:
    """One entry of a device's "Has N reprogrammable keys" list."""

    index: int
    name: str
    default_task: str | None
    mapped_to: str | None
    flags: tuple[str, ...]
    v4: bool  # REPROG_CONTROLS_V4 format; only V4 controls have the divert-keys setting


@dataclass
class ShowDevice:
    device: Device
    receiver_serial: str | None
    wpid: str | None
    features: dict[int, str] = field(default_factory=dict)  # feature id -> name as printed
    keys: list[ShowKey] | None = None  # None: no reprogrammable keys section
    diversion: str | None = None  # live "Key/Button Diversion" value, as printed
    diversion_saved: str | None = None  # "Key/Button Diversion (saved)" value (from Solaar's config.yaml)


@dataclass
class ShowOutput:
    version: str
    devices: list[ShowDevice]


# Receiver lines (2-space indent), from _print_receiver.
_RECEIVER_LINES = [
    re.compile(p)
    for p in (
        r"Device path\s*: .*",
        r"USB id\s*: .*",
        r"Serial\s*: (?P<serial>.*)",
        r"C Pending\s*: .*",
        r"Protocol\s*: Centurion",
        r"Has \d+ (paired )?device\(s\) out of a maximum of \d+\.",
        r"Has \d+ successful pairing\(s\) remaining\.",
        r"Notifications: .*",
        r"Device activity counters: .*",
        r"Supports \d+ dongle features:",
    )
]

# Device lines (5-space indent), from _print_device. Group names are the attributes kept.
_DEVICE_LINES = [
    re.compile(p)
    for p in (
        r"Device path\s*: .*",
        r"WPID\s*: (?P<wpid>.*)",
        r"USB id\s*: .*",
        r"Codename\s*: (?P<codename>.*)",
        r"Kind\s*: (?P<kind>.*)",
        r"Protocol\s*: (?P<protocol>.*)",
        r"Report Rate\s*: .*",
        r"Serial number: (?P<serial>.*)",
        r"Model ID:\s+.*",
        r"Unit ID:\s+(?P<unit_id>.*)",
        r"The power switch is located on the .*\.",
        r"Notifications: .*",
        r"Features: .*",
        r"Battery: .*",
        r"Battery status unavailable\.",
        r"(?P<offline>Device is offline\.)",
        r"(?P<features>Supports (?P<feature_count>\d+) HID\+\+ 2\.0 features:)",
        r"(?P<features_centurion>Supports \d+ dongle \+ \d+ headset features:)",
        r"(?P<keys>Has (?P<key_count>\d+) reprogrammable keys:)",
        r"(?P<remap>Has \d+ persistent remappable keys:)",
        r"(?P<gestures>Has \d+ gesture\(s\), \d+ param\(s\) and \d+ spec\(s\):)",
    )
]

_OFFLINE_PROTOCOL = "unknown (device is offline)"
_FEATURE_RE = re.compile(r" {8,9}(\d+): (.*?)\s+\{([0-9A-Fa-f]{4})\}.*")
_HEADSET_RE = re.compile(r" {7}Headset \(via CentPPBridge\):")
_DIVERSION_RE = re.compile(rf" {{12}}{re.escape(DIVERSION_LABEL)}(?P<saved> \(saved\))?\s*: (?P<value>.*)")
_KEY_V4_RE = re.compile(r" {8,9}(\d+): (.*?)\s*, default: (.*?)\s*=> (.*?)\s*")
_KEY_V2_RE = re.compile(r" {8,9}(\d+): (.*?)\s*=> (.*?)(?: {3,}(.*?))?\s*")
_KEY_FLAGS_RE = re.compile(r" {13}(?:(.*), )?pos:\d+, group:\d+, group mask:.*")
_KEY_REPORTING_RE = re.compile(r" {13}reporting: .*")
_REMAP_RE = re.compile(r" {8,9}\d+: .* => .*")


def _feature_id(name: str, printed: str, builder: _DeviceBuilder, lineno: int) -> int:
    """A feature's ID. For a feature Solaar has no name for ("unknown:1803"), 1.1.20 prints the ID
    byte-swapped ({0318}: show.py reads it with byteorder="little"), so the ID is taken from the name,
    and the printed one must be it or its byte swap."""
    unknown = re.fullmatch(r"unknown:([0-9A-Fa-f]{4})", name)
    if unknown is None:
        return int(printed, 16)
    feature_id = int(unknown[1], 16)
    if int(printed, 16) not in (feature_id, int.from_bytes(feature_id.to_bytes(2), "little")):
        builder.fail(f"feature {name} printed as {{{printed}}}", lineno)
    return feature_id


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _none(value: str | None) -> str | None:
    """Solaar prints a missing value as "None"."""
    value = value.strip() if value is not None else None
    return None if value in (None, "", "None") else value


def _flags(text: str) -> tuple[str, ...]:
    return tuple(f.strip().lower().replace("_", " ") for f in text.split(",") if f.strip())


class _DeviceBuilder:
    def __init__(self, name: str, receiver_serial: str | None, raw: str, start: int):
        self.name = name
        self.receiver_serial = receiver_serial
        self.raw = raw
        self.start = start
        self.attrs: dict[str, str] = {}
        self.section: str | None = None
        self.feature_count: int | None = None
        self.key_count: int | None = None
        self.features: dict[int, str] = {}
        self.keys: list[ShowKey] | None = None
        self.flag_lines: set[int] = set()  # positions in self.keys whose flags line has been seen
        self.diversion: str | None = None
        self.diversion_saved: str | None = None
        self.offline_marker = False

    def fail(self, message: str, lineno: int):
        raise SolaarOutputError(f"device '{self.name}': {message}", self.raw, lineno)

    def top_line(self, text: str, lineno: int):
        for pattern in _DEVICE_LINES:
            m = pattern.fullmatch(text)
            if m:
                break
        else:
            self.fail(f"unknown device line {text!r}", lineno)
        groups = {k: v for k, v in m.groupdict().items() if v is not None}
        self.section = None
        if "offline" in groups:
            self.offline_marker = True
        elif "features" in groups:
            self.section = "features"
            self.feature_count = int(groups["feature_count"])
        elif "features_centurion" in groups:
            self.section = "features"
        elif "keys" in groups:
            self.section = "keys"
            self.key_count = int(groups["key_count"])
            self.keys = []
        elif "remap" in groups:
            self.section = "remap"
        elif "gestures" in groups:
            self.section = "gestures"
        for key in ("wpid", "codename", "kind", "protocol", "serial", "unit_id"):
            if key in groups:
                if key in self.attrs:
                    self.fail(f"duplicate {key} line", lineno)
                self.attrs[key] = groups[key]

    def deep_line(self, line: str, lineno: int):
        if self.section is None:
            # Only firmware lines ("       {kind:11}: name version") are printed deeper outside a section.
            if ":" not in line:
                self.fail(f"unexpected line {line!r}", lineno)
        elif self.section == "features":
            m = _FEATURE_RE.fullmatch(line)
            if m:
                self.features[_feature_id(m[2], m[3], self, lineno)] = m[2]
                return
            m = _DIVERSION_RE.fullmatch(line)
            if m:
                attr = "diversion_saved" if m["saved"] else "diversion"
                if getattr(self, attr) is not None:
                    self.fail(f"duplicate {DIVERSION_LABEL} line", lineno)
                setattr(self, attr, m["value"])
                return
            if _indent(line) < 11 and not _HEADSET_RE.fullmatch(line):
                self.fail(f"unexpected line in features {line!r}", lineno)
        elif self.section == "keys":
            m = _KEY_V4_RE.fullmatch(line)
            if m:
                self.keys.append(ShowKey(int(m[1]), m[2], m[3] or None, m[4] or None, (), True))
                return
            if _KEY_FLAGS_RE.fullmatch(line) or _KEY_REPORTING_RE.fullmatch(line):
                if not self.keys or not self.keys[-1].v4:
                    self.fail(f"key detail line without a key {line!r}", lineno)
                m = _KEY_FLAGS_RE.fullmatch(line)
                if m:
                    last = self.keys[-1]
                    if len(self.keys) - 1 in self.flag_lines:
                        self.fail(f"second flags line for key {last.name!r}", lineno)
                    self.flag_lines.add(len(self.keys) - 1)
                    flags = _flags(m[1] or "")
                    self.keys[-1] = ShowKey(last.index, last.name, last.default_task, last.mapped_to, flags, True)
                return
            m = _KEY_V2_RE.fullmatch(line)
            if m:
                self.keys.append(ShowKey(int(m[1]), m[2], m[3] or None, None, _flags(m[4] or ""), False))
                return
            self.fail(f"unexpected line in reprogrammable keys {line!r}", lineno)
        elif self.section == "remap":
            if not _REMAP_RE.fullmatch(line):
                self.fail(f"unexpected line in persistent remappable keys {line!r}", lineno)
        # gestures: free-form lines, not used

    def build(self, lineno: int) -> ShowDevice:
        protocol = self.attrs.get("protocol")
        if self.offline_marker:
            online = False
        elif protocol is None:
            self.fail("no Protocol line and no 'Device is offline.' line", lineno)
        else:
            online = protocol.strip() != _OFFLINE_PROTOCOL
            if online and not re.fullmatch(r"(HID\+\+|Centurion) \d+\.\d+", protocol.strip()):
                self.fail(f"unknown protocol {protocol!r}", lineno)
        if self.feature_count is not None and len(self.features) != self.feature_count:
            self.fail(f"announced {self.feature_count} features, found {len(self.features)}", lineno)
        if self.keys is not None:
            if len(self.keys) != self.key_count:
                self.fail(f"announced {self.key_count} reprogrammable keys, found {len(self.keys)}", lineno)
            # Every V4 key has a flags line; it carries pos and group even when there are no flags.
            missing = [k.name for i, k in enumerate(self.keys) if k.v4 and i not in self.flag_lines]
            if missing:
                self.fail(f"no flags line for keys {missing}", lineno)
        device = Device(
            name=self.name,
            codename=_none(self.attrs.get("codename")),
            serial=_none(self.attrs.get("serial")),
            unit_id=_none(self.attrs.get("unit_id")),
            kind=_none(self.attrs.get("kind")),
            online=online,
        )
        return ShowDevice(
            device=device,
            receiver_serial=self.receiver_serial,
            wpid=_none(self.attrs.get("wpid")),
            features=self.features,
            keys=self.keys,
            diversion=self.diversion,
            diversion_saved=self.diversion_saved,
        )


def parse_show(text: str) -> ShowOutput:
    """`solaar show` (all devices)."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("solaar version "):
        raise SolaarOutputError("expected 'solaar version X' as the first line", text, 1)
    version = lines[0][len("solaar version ") :].strip()

    devices: list[ShowDevice] = []
    receiver: dict | None = None  # {"serial": ..., "has_devices": bool}
    current: _DeviceBuilder | None = None

    def finish(lineno):
        nonlocal current
        if current is not None:
            devices.append(current.build(lineno))
            current = None

    def next_nonblank(i):
        for j in range(i + 1, len(lines)):
            if lines[j].strip():
                return lines[j]
        return None

    for i, line in enumerate(lines[1:], start=1):
        lineno = i + 1
        if not line.strip():
            continue
        indent = _indent(line)
        text_ = line.strip()
        if indent == 0:
            finish(lineno)
            following = next_nonblank(i)
            if following is not None and _indent(following) == 2:
                receiver = {"serial": None, "has_devices": False}
            elif following is not None and _indent(following) == 5:
                receiver = None  # a device connected directly (USB or Bluetooth)
                current = _DeviceBuilder(text_, None, text, lineno)
            else:
                raise SolaarOutputError(f"unexpected top-level line {line!r}", text, lineno)
        elif indent == 2:
            m = re.fullmatch(r"(\d+): (.*)", text_)
            if m:
                finish(lineno)
                following = next_nonblank(i)
                if m[2] == "Device not found" and (following is None or _indent(following) < 5):
                    continue
                if receiver is not None:
                    receiver["has_devices"] = True
                current = _DeviceBuilder(m[2], receiver["serial"] if receiver else None, text, lineno)
                continue
            if receiver is None or receiver["has_devices"] or current is not None:
                raise SolaarOutputError(f"unexpected receiver line {line!r}", text, lineno)
            for pattern in _RECEIVER_LINES:
                rm = pattern.fullmatch(text_)
                if rm:
                    if rm.groupdict().get("serial") is not None:
                        receiver["serial"] = _none(rm["serial"])
                    break
            else:
                raise SolaarOutputError(f"unknown receiver line {line!r}", text, lineno)
        elif current is not None:
            if indent == 5:
                current.top_line(text_, lineno)
            elif indent > 5:
                current.deep_line(line, lineno)
            else:
                raise SolaarOutputError(f"unexpected indentation {line!r}", text, lineno)
        elif receiver is not None and not receiver["has_devices"] and indent > 2:
            continue  # receiver firmware and dongle feature details
        else:
            raise SolaarOutputError(f"line outside any receiver or device {line!r}", text, lineno)
    finish(len(lines))
    return ShowOutput(version=version, devices=devices)


# ----------------------------------------------------------------------------------------------- config


@dataclass(frozen=True)
class ConfigSetting:
    name: str
    label: str
    description: str | None
    possible_values: str | None
    value: str | None  # None: "? (failed to read from device)"


@dataclass(frozen=True)
class ConfigOutput:
    name: str
    codename: str
    wpid: str | None
    serial: str | None
    settings: list[ConfigSetting]

    def setting(self, name: str) -> ConfigSetting | None:
        return next((s for s in self.settings if s.name == name), None)


_CONFIG_HEADER_RE = re.compile(r"(?P<name>.+) \((?P<codename>[^()]*)\) \[(?P<wpid>[^:\[\]]*):(?P<serial>[^\[\]]*)\]")
_SETTING_VALUE_RE = re.compile(r"(?P<name>[a-z0-9][a-z0-9_-]*) = (?P<value>.*)")
_POSSIBLE_VALUES = "#   possible values: "
_READ_FAILED = "? (failed to read from device)"


def _parse_settings(text: str, lines: list[str], first: int) -> list[ConfigSetting]:
    settings = []
    block: list[tuple[int, str]] = []

    def flush():
        if not block:
            return
        *comments, (value_lineno, value_line) = block
        m = _SETTING_VALUE_RE.fullmatch(value_line)
        if not m:
            raise SolaarOutputError(f"expected 'name = value', got {value_line!r}", text, value_lineno)
        label = description = possible = None
        for lineno, comment in comments:
            if not comment.startswith("# "):
                raise SolaarOutputError(f"expected a '# ' comment line, got {comment!r}", text, lineno)
            if comment.startswith(_POSSIBLE_VALUES) and label is not None and possible is None:
                possible = comment[len(_POSSIBLE_VALUES) :]
            elif label is None:
                label = comment[2:]
            elif description is None and possible is None:
                description = comment[2:]
            else:
                raise SolaarOutputError(f"unexpected comment line {comment!r}", text, lineno)
        if label is None:
            raise SolaarOutputError("setting without a label line", text, value_lineno)
        value = None if m["value"] == _READ_FAILED else m["value"]
        settings.append(ConfigSetting(m["name"], label, description, possible, value))
        block.clear()

    for i in range(first, len(lines)):
        if lines[i].strip():
            block.append((i + 1, lines[i]))
        else:
            flush()
    flush()
    return settings


def parse_config(text: str) -> ConfigOutput:
    """`solaar config <device>`: a header line, then one block per setting."""
    lines = text.splitlines()
    m = _CONFIG_HEADER_RE.fullmatch(lines[0]) if lines else None
    if not m:
        raise SolaarOutputError("expected 'Name (codename) [wpid:serial]' as the first line", text, 1)
    settings = _parse_settings(text, lines, 1)
    if not settings:
        raise SolaarOutputError("no settings", text)
    names = [s.name for s in settings]
    if len(set(names)) != len(names):
        raise SolaarOutputError("a setting is listed twice", text)
    return ConfigOutput(m["name"], m["codename"], _none(m["wpid"]), _none(m["serial"]), settings)


def parse_config_setting(text: str, name: str) -> ConfigSetting:
    """`solaar config <device> <setting>`: one setting block, no header."""
    settings = _parse_settings(text, text.splitlines(), 0)
    if len(settings) != 1 or settings[0].name != name:
        raise SolaarOutputError(f"expected exactly one '{name}' setting", text)
    return settings[0]


# ------------------------------------------------------------------------------------------ divert-keys

_MODE_LABELS = "|".join(re.escape(m.value) for m in SETTABLE_MODES)
# Control names never contain commas or braces (special_keys.CONTROL); "unknown:00A1" fallbacks contain a colon.
_DIVERT_ITEM_RE = re.compile(rf"(?P<key>[^,{{}}]+?):(?P<mode>{_MODE_LABELS})(?:, |$)")


def parse_divert_map(value: str, raw: str | None = None) -> dict[str, DivertMode]:
    """A printed divert-keys value: "{Middle Button:Regular, Back Button:Diverted}" (ChoicesMapValidator.to_string)."""
    raw = value if raw is None else raw
    if not (value.startswith("{") and value.endswith("}")):
        raise SolaarOutputError(f"expected a {{control:mode, ...}} map, got {value!r}", raw)
    body = value[1:-1]
    result: dict[str, DivertMode] = {}
    pos = 0
    while pos < len(body):
        m = _DIVERT_ITEM_RE.match(body, pos)
        if not m:
            raise SolaarOutputError(f"unrecognized divert-keys entry at {body[pos:]!r}", raw)
        if m["key"] in result:
            raise SolaarOutputError(f"control {m['key']!r} listed twice", raw)
        result[m["key"]] = DivertMode(m["mode"])
        pos = m.end()
    return result


def parse_divert_keys(text: str) -> dict[str, DivertMode]:
    """`solaar config <device> divert-keys`: the live per-control diversion read from the device."""
    setting = parse_config_setting(text, DIVERT_SETTING)
    if setting.label != DIVERSION_LABEL:
        raise SolaarOutputError(f"unexpected label {setting.label!r}", text)
    if setting.value is None:
        raise SolaarOutputError("Solaar failed to read divert-keys from the device", text)
    return parse_divert_map(setting.value, text)


_SET_DIVERT_RE = re.compile(
    r"Setting divert-keys of (?P<device>.+) key NamedInt\((?P<cid>\d+), (?P<q1>['\"])(?P<control>.+)(?P=q1)\)"
    r" to NamedInt\((?P<value>\d+), (?P<q2>['\"])(?P<mode>.+)(?P=q2)\)"
)


def parse_set_divert(text: str) -> tuple[str, str, DivertMode]:
    """Output of `solaar config <device> divert-keys <control> <mode>`: (device name, control, mode)."""
    lines = [line for line in text.splitlines() if line.strip()]
    m = _SET_DIVERT_RE.fullmatch(lines[0]) if len(lines) == 1 else None
    if not m or m["mode"] not in {mode.value for mode in SETTABLE_MODES}:
        raise SolaarOutputError("expected one 'Setting divert-keys of ... key ... to ...' line", text)
    return m["device"], m["control"], DivertMode(m["mode"])


# --------------------------------------------------------------------------------------------- controls


def controls_from_show(entry: ShowDevice, raw: str) -> list[Control]:
    """Combine a device's reprogrammable keys with its live and saved divert-keys values.

    A key is divertable if Solaar's divert-keys setting covers it: V4 controls flagged divertable and
    not virtual (DivertKeys.validator_class.build). Raw-XY controls also offer Mouse Gestures, plus
    Sliding DPI if the device has ADJUSTABLE_DPI. The divertable set derived from the flags must equal
    the controls in Solaar's own divert-keys value, or the output is rejected.
    """
    name = entry.device.name
    keys = entry.keys or []
    divertable = {k.name for k in keys if k.v4 and "divertable" in k.flags and "virtual" not in k.flags}

    live: dict[str, DivertMode] | None = None
    if entry.diversion is not None:
        if entry.diversion.startswith(("HID++ error", "AssertionError")):
            live = None  # Solaar could not read it; modes stay unknown
        else:
            live = parse_divert_map(entry.diversion, raw)
            if set(live) != divertable:
                raise SolaarOutputError(
                    f"device '{name}': divert-keys lists {sorted(live)}, divertable keys are {sorted(divertable)}", raw
                )
    elif divertable:
        raise SolaarOutputError(f"device '{name}': divertable keys but no {DIVERSION_LABEL} line", raw)
    saved = parse_divert_map(entry.diversion_saved, raw) if entry.diversion_saved is not None else {}

    controls = []
    for key in keys:
        if key.name not in divertable:
            controls.append(Control(key.name, False, None, (), None, key.flags))
            continue
        modes = (DivertMode.REGULAR, DivertMode.DIVERTED)
        if "raw xy" in key.flags:
            modes += (DivertMode.MOUSE_GESTURES,)
            if ADJUSTABLE_DPI in entry.features:
                modes += (DivertMode.SLIDING_DPI,)
        mode = live.get(key.name) if live is not None else None
        if mode is DivertMode.DIVERTED and DivertMode.MOUSE_GESTURES in modes:
            mode = DivertMode.DIVERTED_MODE_UNKNOWN
        elif mode is not None and mode not in modes:
            raise SolaarOutputError(f"device '{name}': {key.name!r} reads {mode.value!r}, not one of its modes", raw)
        controls.append(Control(key.name, True, mode, modes, saved.get(key.name), key.flags))
    return controls
