# SPDX-License-Identifier: GPL-2.0-or-later
"""Read rules.yaml into a RuleSet and serialize a RuleSet the way Solaar saves it.

Formatting mirrors `diversion._save_config_rule_file` (identical in Solaar 1.1.14 and 1.1.20): a
`%YAML 1.3` line when there are rules, then `yaml.dump_all` with `explicit_start`, `explicit_end`
and `default_flow_style=False`, after a `convert` pass that writes scalar-only lists in flow style.

Solaar's `convert` also collapses every one-scalar list to the scalar. Heliostat does not: it writes
each argument in the shape it was loaded (deviation D2 in docs/decisions.md), and a component built in
code is already in Solaar's saved (collapsed) shape. So for files Solaar saved and for rules Heliostat
builds, the output still matches Solaar's save byte for byte, apart from D1.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from heliostat.model import CLICK_ACTIONS, And, Component, KeyPress, Later, Not, Or, Raw, Rule, RuleSet

YAML_HEADER = "%YAML 1.3\n"

# Solaar's convert() writes lists of these in flow style. bool is an int; None is not a scalar.
_SCALARS = (int, str, float)


class RulesParseError(Exception):
    """rules.yaml is not valid YAML.

    `line` and `column` are 1-based (None if PyYAML gave no position). `documents_parsed` is how many
    documents loaded before the error, which is how many rules Solaar is running from this file:
    it keeps those, logs the error, and drops the rest on its next save.
    """

    def __init__(self, message: str, line: int | None, column: int | None, documents_parsed: int, path=None):
        self.message = message
        self.line = line
        self.column = column
        self.documents_parsed = documents_parsed
        self.path = path
        where = f"line {line}, column {column}" if line is not None else "unknown position"
        name = f"{path}: " if path is not None else ""
        super().__init__(f"{name}{where}: {message} ({documents_parsed} rule(s) parsed before the error)")


def loads(data: str | bytes, path=None) -> RuleSet:
    """Parse rules.yaml text with `yaml.safe_load_all`, as Solaar does. Strict: no partial results."""
    documents = []
    try:
        for document in yaml.safe_load_all(data):
            documents.append(document)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
        line, column = (mark.line + 1, mark.column + 1) if mark is not None else (None, None)
        raise RulesParseError(_one_line(e), line, column, len(documents), path) from e
    return RuleSet.from_yaml(documents)


def load(path) -> RuleSet:
    path = Path(path)
    return loads(path.read_bytes(), path)


def _one_line(error: yaml.YAMLError) -> str:
    if isinstance(error, yaml.MarkedYAMLError):
        parts = [error.context, error.problem]
        return "; ".join(p for p in parts if p)
    return str(error).splitlines()[0] if str(error) else type(error).__name__


class _InlineList(list):
    """A list written in flow style (Solaar's `inline_list`)."""


class _Dumper(yaml.Dumper):
    """yaml.Dumper (what Solaar's yaml.dump_all uses) plus Solaar's inline_list representer.

    A subclass, so the representer does not leak into the global yaml.Dumper the way Solaar's does.
    """


_Dumper.add_representer(
    _InlineList, lambda dumper, data: dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)
)


def _convert(elem: Any) -> Any:
    """Solaar's convert() without its one-scalar-list collapse: scalar-only lists in flow style."""
    if isinstance(elem, list):
        if all(isinstance(c, _SCALARS) for c in elem):
            return _InlineList(elem)
        return [_convert(c) for c in elem]
    if isinstance(elem, dict):
        return {k: _convert(v) for k, v in elem.items()}
    return elem


def _sequence(items: list[Any]) -> list[Any]:
    """Already-converted items as a list, flow style if all scalars."""
    return _InlineList(items) if all(isinstance(i, _SCALARS) for i in items) else list(items)


def _dump_component(component: Component) -> Any:
    if isinstance(component, Raw):
        return _convert(component.data)
    if isinstance(component, (Rule, Or, And)):
        return {component.TYPE: _sequence([_dump_component(c) for c in component.components])}
    if isinstance(component, Not):
        inner = _dump_component(component.component)
        return {component.TYPE: [inner] if component.listed else inner}
    if isinstance(component, Later):
        if not component.components:
            return _convert(component.to_yaml())
        return {component.TYPE: _sequence([component.delay, *(_dump_component(c) for c in component.components)])}
    if isinstance(component, KeyPress):
        arg = component.to_yaml()[component.TYPE]
        if isinstance(arg, list) and len(arg) == 2 and isinstance(arg[0], str) and arg[1] in CLICK_ACTIONS:
            # [key, action]: Solaar's save writes this pair in block style (it comes from [[key], action]
            # with the inner list collapsed). Flow style loads the same, so use Solaar's style.
            return {component.TYPE: list(arg)}
    return _convert(component.to_yaml())


def _dump_document(rule: Rule | Raw) -> Any:
    if isinstance(rule, Raw):
        return _convert(rule.data)
    return _sequence([_dump_component(c) for c in rule.components])


def component_text(component: Component) -> str:
    """One component as YAML text in Solaar's style, for editing (`Key: [Back Button, pressed]`)."""
    return _dump_one(_dump_component(component))


def rule_text(rule: Rule | Raw) -> str:
    """A top-level rule as the YAML text of its document, for editing (a block list of components)."""
    return _dump_one(_dump_document(rule))


def _dump_one(value: Any) -> str:
    text = yaml.dump(value, Dumper=_Dumper, default_flow_style=False)
    return text.removesuffix("...\n")  # PyYAML ends a bare top-level scalar with a document end marker


def loads_value(text: str) -> Any:
    """Parse YAML text that holds one value (one document) with the loader Solaar uses."""
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None) or getattr(e, "context_mark", None)
        line, column = (mark.line + 1, mark.column + 1) if mark is not None else (None, None)
        raise RulesParseError(_one_line(e), line, column, 0) from e
    if len(documents) > 1:
        raise RulesParseError("more than one YAML document", None, None, 1)
    return documents[0] if documents else None


def dumps(ruleset: RuleSet) -> str:
    """Serialize like Solaar's `_save_config_rule_file`."""
    documents = [_dump_document(r) for r in ruleset.rules]
    if not documents:
        return ""
    body = yaml.dump_all(documents, Dumper=_Dumper, explicit_start=True, explicit_end=True, default_flow_style=False)
    return YAML_HEADER + body
