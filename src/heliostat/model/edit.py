# SPDX-License-Identifier: GPL-2.0-or-later
"""Edits to a RuleSet by rule path, each returning a new RuleSet and leaving the old one unchanged.

A path is the one Problem.rule_path uses: (i,) is top-level rule i, then component indexes inside
Rule, Or, And and Later (a Later's delay is not a component), and 0 for the component inside a Not.
Only the components on the path are touched; everything else is copied as it is, so unedited
components keep the shapes they were loaded in (deviation D2).
"""

from __future__ import annotations

import copy

from heliostat.model.components import And, Component, Later, Not, Or, Raw, Rule
from heliostat.model.ruleset import RuleSet

RulePath = tuple[int, ...]


class EditError(ValueError):
    """The edit does not apply at that path."""


def children(component: Component) -> list[Component] | None:
    """The list of components a container holds, which insert, remove and move work on.

    None for a leaf, a Raw, and a Not (its one component can only be replaced).
    """
    if isinstance(component, (Rule, Or, And, Later)):
        return component.components
    return None


def get(ruleset: RuleSet, path: RulePath) -> Component:
    """The top-level rule or component at path."""
    if not path:
        raise EditError("empty path")
    try:
        node: Component = ruleset.rules[path[0]]
        for index in path[1:]:
            if isinstance(node, Not):
                if index != 0:
                    raise IndexError(index)
                node = node.component
            else:
                items = children(node)
                if items is None:
                    raise EditError(f"{path}: {_kind(node)} has no components")
                node = items[index]
    except IndexError:
        raise EditError(f"no component at {path}") from None
    return node


def _list_at(ruleset: RuleSet, parent: RulePath) -> list:
    if not parent:
        return ruleset.rules
    node = get(ruleset, parent)
    items = children(node)
    if items is None:
        raise EditError(f"{parent}: {_kind(node)} does not hold a list of components")
    return items


def _kind(node: Component) -> str:
    if isinstance(node, Raw):
        return "an unrecognized component"
    return f"a {node.TYPE} component"


def replace(ruleset: RuleSet, path: RulePath, new: Component) -> RuleSet:
    """Put `new` at path. At the top level `new` must be a Rule or a Raw (a whole document)."""
    if len(path) == 1 and not isinstance(new, (Rule, Raw)):
        raise EditError("a top-level rule must be a Rule or a Raw document")
    out = copy.deepcopy(ruleset)
    get(out, path)  # check it exists
    parent = path[:-1]
    if parent and isinstance(node := get(out, parent), Not):
        node.component = copy.deepcopy(new)
    else:
        _list_at(out, parent)[path[-1]] = copy.deepcopy(new)
    return out


def insert(ruleset: RuleSet, path: RulePath, new: Component) -> RuleSet:
    """Insert `new` so that it ends up at path (the last index may be one past the end)."""
    if len(path) == 1 and not isinstance(new, (Rule, Raw)):
        raise EditError("a top-level rule must be a Rule or a Raw document")
    out = copy.deepcopy(ruleset)
    items = _list_at(out, path[:-1])
    if not 0 <= path[-1] <= len(items):
        raise EditError(f"no position {path}")
    items.insert(path[-1], copy.deepcopy(new))
    return out


def remove(ruleset: RuleSet, path: RulePath) -> RuleSet:
    out = copy.deepcopy(ruleset)
    items = _list_at(out, path[:-1])
    if not 0 <= path[-1] < len(items):
        raise EditError(f"no component at {path}")
    del items[path[-1]]
    return out


def can_move(ruleset: RuleSet, path: RulePath, delta: int) -> bool:
    try:
        items = _list_at(ruleset, path[:-1])
    except EditError:
        return False
    return 0 <= path[-1] < len(items) and 0 <= path[-1] + delta < len(items)


def move(ruleset: RuleSet, path: RulePath, delta: int) -> tuple[RuleSet, RulePath]:
    """Move the item at path by `delta` places among its siblings; returns the new set and its new path."""
    if not can_move(ruleset, path, delta):
        raise EditError(f"cannot move {path} by {delta}")
    out = copy.deepcopy(ruleset)
    items = _list_at(out, path[:-1])
    item = items.pop(path[-1])
    new_index = path[-1] + delta
    items.insert(new_index, item)
    return out, (*path[:-1], new_index)


def can_remove(ruleset: RuleSet, path: RulePath) -> bool:
    """True unless path is the component inside a Not (remove the Not instead)."""
    if len(path) > 1:
        try:
            if isinstance(get(ruleset, path[:-1]), Not):
                return False
        except EditError:
            return False
    try:
        get(ruleset, path)
    except EditError:
        return False
    return True
