# SPDX-License-Identifier: GPL-2.0-or-later
"""The user's rules: one entry per YAML document in rules.yaml."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from heliostat.model.components import Raw, Rule


def rule_from_document(document: Any) -> Rule | Raw:
    """A YAML document is a list of components. Anything else is kept as a top-level `Raw`."""
    if isinstance(document, list):
        return Rule._from_arg(document)
    return Raw(copy.deepcopy(document), reason="rule document is not a list of components")


def rule_to_document(rule: Rule | Raw) -> Any:
    if isinstance(rule, Raw):
        return rule.to_yaml()
    return rule._arg()


@dataclass
class RuleSet:
    """The user rules held in a rules file, in order. Solaar's built-in rules are not included."""

    rules: list[Rule | Raw] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, documents: list[Any]) -> RuleSet:
        return cls([rule_from_document(d) for d in documents])

    def to_yaml(self) -> list[Any]:
        return [rule_to_document(r) for r in self.rules]
