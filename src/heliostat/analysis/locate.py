# SPDX-License-Identifier: GPL-2.0-or-later
"""Line numbers for rule paths, from the YAML node tree of the text a RuleSet was loaded from."""

from __future__ import annotations

from typing import Any

import yaml

from heliostat.model import And, Later, Not, Or, Rule, RuleSet


def locations(data: str | bytes, ruleset: RuleSet) -> dict[tuple[int, ...], int]:
    """1-based line of every component the model holds, keyed by rule path (see Problem.rule_path).

    `ruleset` must be what `rulesfile.loads(data)` returned.
    """
    out: dict[tuple[int, ...], int] = {}
    for i, (node, rule) in enumerate(zip(yaml.compose_all(data, Loader=yaml.SafeLoader), ruleset.rules, strict=True)):
        if node is None:  # an empty document has no node; place it nowhere rather than guess
            continue
        out[(i,)] = node.start_mark.line + 1
        if isinstance(rule, Rule) and isinstance(node, yaml.SequenceNode):
            _items(node.value, rule.components, (i,), out)
    return out


def _items(nodes: list[Any], components: list[Any], path: tuple[int, ...], out: dict) -> None:
    for k, (node, component) in enumerate(zip(nodes, components, strict=True)):
        _component(node, component, (*path, k), out)


def _component(node: Any, component: Any, path: tuple[int, ...], out: dict) -> None:
    out[path] = node.start_mark.line + 1
    if not (isinstance(node, yaml.MappingNode) and len(node.value) == 1):
        return
    ((_, value),) = node.value
    if isinstance(component, (Rule, Or, And)) and isinstance(value, yaml.SequenceNode):
        _items(value.value, component.components, path, out)
    elif isinstance(component, Later) and isinstance(value, yaml.SequenceNode):
        _items(value.value[1:], component.components, path, out)
    elif isinstance(component, Not):
        inner = value.value[0] if isinstance(value, yaml.SequenceNode) else value
        _component(inner, component.component, (*path, 0), out)
