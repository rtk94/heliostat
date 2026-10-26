# SPDX-License-Identifier: GPL-2.0-or-later
"""What the rule list and the advanced tree show for a rule. No Qt here, so it is tested on its own.

Simple rules get `describe()`. Every other rule gets a compact one-line form built from the components
as the model holds them (so in the shapes they were loaded, deviation D2): `Type: argument` for a leaf,
with the argument in YAML flow style, and `Type(...)` around the contents of Rule, Or, And, Not and
Later. Components in a sequence are separated by `; `, alternatives in an Or or And by `, `.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml

from heliostat.model import And, Component, Later, Not, Or, Raw, Rule
from heliostat.simple import describe, recognize


def rule_summary(rule: Rule | Raw, device_names: Mapping[Any, str] | None = None) -> str:
    """One line for the rule list: the plain-language description of a simple rule, else the compact form."""
    simple = recognize(rule) if isinstance(rule, Rule) else None
    if simple is not None:
        return describe(simple, device_names)
    if isinstance(rule, Raw):
        return f"(not a list of components) {flow(rule.data)}"
    if not rule.components:
        return "(empty rule)"
    return "; ".join(compact(c) for c in rule.components)


def compact(component: Component) -> str:
    """One line for a component and everything inside it."""
    if isinstance(component, Rule):
        return f"Rule({'; '.join(compact(c) for c in component.components)})"
    if isinstance(component, (Or, And)):
        return f"{component.TYPE}({', '.join(compact(c) for c in component.components)})"
    if isinstance(component, Not):
        return f"Not({compact(component.component)})"
    if isinstance(component, Later):
        inside = "; ".join(compact(c) for c in component.components)
        return f"Later({flow(component.delay)}: {inside})" if inside else f"Later({flow(component.delay)})"
    if isinstance(component, Raw):
        return _raw_text(component)
    ((name, arg),) = component.to_yaml().items()
    return f"{name}: {flow(arg)}"


def flow(value: Any) -> str:
    """A loaded YAML value on one line, in flow style."""
    try:
        text = yaml.safe_dump(value, default_flow_style=True, width=float("inf"), allow_unicode=True, sort_keys=False)
    except yaml.YAMLError:
        return repr(value)
    lines = [line for line in text.splitlines() if line != "..."]
    return " ".join(lines)


def _raw_text(component: Raw) -> str:
    data = component.data
    if isinstance(data, dict) and len(data) == 1:
        ((name, arg),) = data.items()
        return f"{flow(name)}: {flow(arg)}"
    return flow(data)


@dataclass
class Node:
    """One row of the advanced tree. `path` is the component's rule path (see Problem.rule_path)."""

    path: tuple[int, ...]
    label: str
    value: str = ""
    tooltip: str = ""
    unrecognized: bool = False
    children: list[Node] = field(default_factory=list)


def rule_nodes(rule: Rule | Raw, index: int) -> list[Node]:
    """The top-level rows of the advanced tree for top-level rule `index`."""
    if isinstance(rule, Raw):
        return [Node((index,), "(not a rule)", flow(rule.data), rule.reason, unrecognized=True)]
    return [_node(c, (index, k)) for k, c in enumerate(rule.components)]


def _node(component: Component, path: tuple[int, ...]) -> Node:
    if isinstance(component, Rule):
        return Node(path, "Rule", "", children=_nodes(component.components, path))
    if isinstance(component, Or):
        return Node(path, "Or", "any of", children=_nodes(component.components, path))
    if isinstance(component, And):
        return Node(path, "And", "all of", children=_nodes(component.components, path))
    if isinstance(component, Not):
        return Node(path, "Not", "", children=[_node(component.component, (*path, 0))])
    if isinstance(component, Later):
        return Node(path, "Later", f"after {flow(component.delay)} s", children=_nodes(component.components, path))
    if isinstance(component, Raw):
        data = component.data
        if isinstance(data, dict) and len(data) == 1:
            ((name, arg),) = data.items()
            label, value = flow(name), flow(arg)
        else:
            label, value = "(unrecognized)", flow(data)
        return Node(path, label, value, f"Not understood by Heliostat, kept as written: {component.reason}", True)
    ((name, arg),) = component.to_yaml().items()
    return Node(path, name, flow(arg))


def _nodes(components: list[Component], path: tuple[int, ...]) -> list[Node]:
    return [_node(c, (*path, k)) for k, c in enumerate(components)]
