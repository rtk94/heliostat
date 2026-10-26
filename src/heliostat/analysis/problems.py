# SPDX-License-Identifier: GPL-2.0-or-later
"""What lint reports: a Problem per finding, with an optional Fix that lint offers but never applies."""

from __future__ import annotations

import enum
from dataclasses import dataclass

from heliostat.model import Component

CODES = {
    "HL000": "parse-error",
    "HL001": "undiverted-control",
    "HL002": "unknown-control",
    "HL003": "duplicate-binding",
    "HL004": "unreachable",
    "HL005": "depress-without-release",
    "HL006": "wayland-process",
    "HL007": "spaced-feature-name",
    "HL008": "lost-feature",
    "HL009": "load-abort",
    "HL010": "solaar-save-hazard",
}


class Severity(enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"  # not a problem in the rules: a check that could not run, and why

    @property
    def rank(self) -> int:
        return {Severity.ERROR: 0, Severity.WARNING: 1, Severity.NOTE: 2}[self]


@dataclass(frozen=True)
class Fix:
    """A suggested fix. `command` is a `solaar` command line that applies it; `replacement` is a
    component to put in place of the one at the problem's rule_path."""

    description: str
    command: tuple[str, ...] | None = None
    replacement: Component | None = None


@dataclass(frozen=True)
class Problem:
    """One finding.

    `rule_path` locates it in the RuleSet: () for the whole file, (i,) for top-level rule i, then
    component indexes: `Rule`/`Or`/`And`/`Later` components by position (a Later's delay is not a
    component), and 0 for the component inside a `Not`. All indexes are 0-based.
    """

    severity: Severity
    rule_path: tuple[int, ...]
    code: str
    message: str
    fix: Fix | None = None

    @property
    def name(self) -> str:
        return CODES.get(self.code, "")
