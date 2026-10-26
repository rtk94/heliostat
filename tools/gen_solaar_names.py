# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate src/heliostat/solaar/names.py from the pinned Solaar checkouts in .solaar/<tag>/.

Reads (never imports) each tag's `logitech_receiver/special_keys.py` (the CONTROL table, plus the G, M
and MR keys it adds by hand), `logitech_receiver/hidpp20_constants.py` (the SupportedFeature enum) and
`logitech_receiver/diversion.py` (the TESTS and MOUSE_GESTURE_TESTS names, MouseGesture.MOVEMENTS).
All three are GPL-2.0-or-later in both tags.

Usage: .venv/bin/python tools/gen_solaar_names.py [--check]
With --check, exit 1 if names.py is not what this script would write.
"""

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAGS = ("1.1.14", "1.1.20")
OUT = ROOT / "src" / "heliostat" / "solaar" / "names.py"

# special_keys.py adds these after building CONTROL; the generator checks the source still says so.
_EXTRA_PATTERNS = (
    r'for i in range\(1, 33\):.*\n    CONTROL\[0x1000 \+ i\] = (?:"G" \+ str\(i\)|f"G\{str\(i\)\}")\n',
    r'for i in range\(1, 9\):.*\n    CONTROL\[0x1100 \+ i\] = (?:"M" \+ str\(i\)|f"M\{str\(i\)\}")\n',
    r'\nCONTROL\[0x1200\] = "MR"',
)


def _extra_controls() -> dict[str, int]:
    extra = {f"G{i}": 0x1000 + i for i in range(1, 33)}
    extra.update({f"M{i}": 0x1100 + i for i in range(1, 9)})
    extra["MR"] = 0x1200
    return extra


def controls(tag: str) -> dict[str, int]:
    path = ROOT / ".solaar" / tag / "lib" / "logitech_receiver" / "special_keys.py"
    source = path.read_text()
    for pattern in _EXTRA_PATTERNS:
        if not re.search(pattern, source):
            sys.exit(f"{path}: expected source lines not found: {pattern}")
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and [t.id for t in node.targets if isinstance(t, ast.Name)] == ["CONTROL"]:
            call = node.value
            if not (isinstance(call, ast.Call) and len(call.args) == 1 and isinstance(call.args[0], ast.Dict)):
                sys.exit(f"{path}: CONTROL is not NamedInts({{...}})")
            table = {
                ast.literal_eval(k): ast.literal_eval(v)
                for k, v in zip(call.args[0].keys, call.args[0].values, strict=True)
            }
            return {**table, **_extra_controls()}
    sys.exit(f"{path}: no CONTROL assignment")


def features(tag: str) -> dict[str, int]:
    path = ROOT / ".solaar" / tag / "lib" / "logitech_receiver" / "hidpp20_constants.py"
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.ClassDef) and node.name == "SupportedFeature":
            return {
                stmt.targets[0].id: ast.literal_eval(stmt.value)
                for stmt in node.body
                if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name)
            }
    sys.exit(f"{path}: no SupportedFeature class")


def _diversion(tag: str) -> tuple[list[str], list[str], list[str]]:
    """TESTS keys, MOUSE_GESTURE_TESTS keys and MouseGesture.MOVEMENTS, in source order."""
    path = ROOT / ".solaar" / tag / "lib" / "logitech_receiver" / "diversion.py"
    found = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("TESTS", "MOUSE_GESTURE_TESTS") and isinstance(node.value, ast.Dict):
                found[node.targets[0].id] = [ast.literal_eval(k) for k in node.value.keys]
        if isinstance(node, ast.ClassDef) and node.name == "MouseGesture":
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and [t.id for t in stmt.targets] == ["MOVEMENTS"]:
                    found["MOVEMENTS"] = ast.literal_eval(stmt.value)
    if set(found) != {"TESTS", "MOUSE_GESTURE_TESTS", "MOVEMENTS"}:
        sys.exit(f"{path}: found only {sorted(found)}")
    return found["TESTS"], found["MOUSE_GESTURE_TESTS"], found["MOVEMENTS"]


SOURCES = ("special_keys.py", "hidpp20_constants.py", "diversion.py")


def copyright_lines(source: str) -> list[str]:
    """The Copyright lines of a source file's leading `##` comment block, in every tag, deduplicated."""
    lines: list[str] = []
    for tag in TAGS:
        path = ROOT / ".solaar" / tag / "lib" / "logitech_receiver" / source
        found = []
        for line in path.read_text().splitlines():
            if not line.startswith("##"):
                break
            text = line.removeprefix("##").strip()
            if text.lower().startswith("copyright"):
                found.append(text)
        if not found:
            sys.exit(f"{path}: no Copyright line in the header")
        lines += [line for line in found if line not in lines]
    return lines


def _commit(tag: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT / ".solaar" / tag), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return out.stdout.strip() or "unknown"


def _table(name: str, tables: dict[str, dict[str, int]]) -> list[str]:
    lines = [f"{name}: dict[str, dict[str, int]] = {{"]
    for tag, table in tables.items():
        lines.append(f'    "{tag}": {{')
        lines += [f'        "{k}": 0x{v:04X},' for k, v in table.items()]
        lines.append("    },")
    lines.append("}")
    return lines


def _names(name: str, tables: dict[str, list[str]]) -> list[str]:
    lines = [f"{name}: dict[str, tuple[str, ...]] = {{"]
    for tag, names in tables.items():
        lines.append(f'    "{tag}": (')
        lines += [f"        {n!r}," for n in names]
        lines.append("    ),")
    lines.append("}")
    return lines


def render() -> str:
    head = [
        "# SPDX-License-Identifier: GPL-2.0-or-later",
        '"""Solaar\'s control and feature names, per pinned Solaar tag. Generated; do not edit.',
        "",
        "Written by tools/gen_solaar_names.py from .solaar/<tag>/lib/logitech_receiver/special_keys.py",
        "(CONTROL, plus the G1-G32, M1-M8 and MR keys it adds), hidpp20_constants.py (SupportedFeature) and",
        "diversion.py (TESTS, MOUSE_GESTURE_TESTS, MouseGesture.MOVEMENTS), all GPL-2.0-or-later. Names are",
        "exactly as in Solaar's source, in source order: CONTROL's are the NamedInts keys (underscore",
        "spelling, `__` for `/`).",
        "",
    ]
    head += [f"Solaar {tag}: commit {_commit(tag)}" for tag in TAGS]
    head += [
        "",
        "Derived from Solaar (https://github.com/pwr-Solaar/Solaar), GPL-2.0-or-later. Notices from the",
        "source files:",
    ]
    for source in SOURCES:
        head += ["", f"lib/logitech_receiver/{source}:"]
        head += [f"    {line}" for line in copyright_lines(source)]
    head += ['"""', "", "# fmt: off"]
    diversion = {t: _diversion(t) for t in TAGS}
    body = (
        _table("CONTROLS", {t: controls(t) for t in TAGS}) + [""] + _table("FEATURES", {t: features(t) for t in TAGS})
    )
    body += [""] + _names("TESTS", {t: d[0] for t, d in diversion.items()})
    body += [""] + _names("MOUSE_GESTURE_TESTS", {t: d[1] for t, d in diversion.items()})
    body += [""] + _names("MOVEMENTS", {t: d[2] for t, d in diversion.items()})
    return "\n".join(head + body + ["# fmt: on", ""])


def main(argv: list[str]) -> int:
    text = render()
    if argv == ["--check"]:
        if OUT.read_text() != text:
            print(f"{OUT} is out of date; run tools/gen_solaar_names.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
