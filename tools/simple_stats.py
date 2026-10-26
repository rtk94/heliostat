#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Report which top-level rules in the rules fixtures the simple editor recognizes.

Usage: tools/simple_stats.py [FILE...]   (default: tests/fixtures/rules/*.yaml)

Prints describe() for each recognized rule, and the shape (component types in order) and reason
for each rule that is not.
"""

import sys
from pathlib import Path

from heliostat.model import Component, Raw, Rule
from heliostat.rulesfile import RulesParseError, load
from heliostat.simple import describe, not_simple_reason, recognize

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rules"


def shape(component: Component) -> str:
    if isinstance(component, Raw):
        return f"Raw({component.type_name or type(component.data).__name__})"
    if isinstance(component, Rule):
        return "[" + ", ".join(shape(c) for c in component.components) + "]"
    return component.TYPE


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or sorted(FIXTURES.glob("*.yaml"))
    total = simple = 0
    recognized, unrecognized = [], []
    for path in paths:
        try:
            ruleset = load(path)
        except RulesParseError as e:
            print(f"{path.name}: not parsed ({e.message}), skipped")
            continue
        for i, rule in enumerate(ruleset.rules, 1):
            total += 1
            where = f"{path.name} #{i}"
            s = recognize(rule)
            if s is not None:
                simple += 1
                recognized.append(f"{where}: {describe(s)}")
            else:
                unrecognized.append(f"{where}: {shape(rule)}  ({not_simple_reason(rule)})")
    print(f"\nRecognized as simple: {simple}/{total} ({simple / total:.0%})" if total else "No rules.")
    print("\nRecognized:")
    print("\n".join(f"  {line}" for line in recognized))
    print("\nNot simple:")
    print("\n".join(f"  {line}" for line in unrecognized))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
