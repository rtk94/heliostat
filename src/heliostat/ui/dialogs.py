# SPDX-License-Identifier: GPL-2.0-or-later
"""Dialogs: YAML text for a component or rule, a new simple rule, and a file changed on disk."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from heliostat.model import Component, Raw, Rule, component_from_yaml
from heliostat.model.ruleset import rule_from_document
from heliostat.rulesfile import ExternalChange, RulesParseError, loads_value
from heliostat.simple import generate
from heliostat.ui.simple_editor import SimpleEditor


def _fixed_font():
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)


def parse_component(text: str) -> tuple[Component, str]:
    """A component from YAML text, and a note on how Heliostat reads it. Raises ValueError."""
    try:
        value = loads_value(text)
    except RulesParseError as e:
        raise ValueError(str(e)) from e
    component = component_from_yaml(value)
    if isinstance(component, Raw):
        return component, f"Not a component Heliostat recognizes ({component.reason}); it will be kept as written."
    return component, f"{component.TYPE} component."


def parse_rule(text: str) -> tuple[Rule | Raw, str]:
    """A top-level rule (a YAML document) from YAML text. Raises ValueError."""
    try:
        value = loads_value(text)
    except RulesParseError as e:
        raise ValueError(str(e)) from e
    rule = rule_from_document(value)
    if isinstance(rule, Raw):
        return rule, "Not a list of components; Solaar cannot load this rule. It will be kept as written."
    raws = sum(isinstance(c, Raw) for c in rule.components)
    note = f"Rule with {len(rule.components)} component(s)."
    if raws:
        note += f" {raws} not recognized by Heliostat; they will be kept as written."
    return rule, note


class YamlDialog(QDialog):
    """Edit YAML text. `parse(text)` returns (value, note) or raises ValueError; OK needs a value."""

    def __init__(self, parent, title: str, text: str, parse: Callable[[str], tuple[Any, str]]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 360)
        self.parse = parse
        self.value: Any = None
        layout = QVBoxLayout(self)
        self.editor = QPlainTextEdit()
        self.editor.setFont(_fixed_font())
        self.editor.setPlainText(text)
        self.editor.textChanged.connect(self._check)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self._check()

    def _check(self) -> None:
        try:
            self.value, note = self.parse(self.editor.toPlainText())
        except ValueError as e:
            self.value = None
            self.status.setText(f"Not valid: {e}")
            self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return
        self.status.setText(note)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)


class SimpleRuleDialog(QDialog):
    """A new simple rule. `rule` is the generated Rule after accept()."""

    def __init__(self, parent, devices, device_names):
        super().__init__(parent)
        self.setWindowTitle("New rule")
        self.resize(560, 620)
        self.rule: Rule | None = None
        layout = QVBoxLayout(self)
        self.editor = SimpleEditor(min_actions=0)
        self.editor.set_devices(devices, device_names)
        self.editor.edited.connect(self._check)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.buttons)
        self._check()

    def _check(self, *_args) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.editor.problem() is None)

    def _accept(self) -> None:
        if self.editor.problem() is None:
            self.rule = generate(self.editor.current())
            self.accept()


class ExternalChangeDialog(QDialog):
    """The rules file changed on disk. `choice` is "reload", "overwrite" or "cancel"."""

    def __init__(self, parent, change: ExternalChange, dirty: bool):
        super().__init__(parent)
        self.setWindowTitle("Rules file changed on disk")
        self.resize(720, 480)
        self.choice = "cancel"
        layout = QVBoxLayout(self)
        intro = QLabel(
            f"{change} (perhaps Solaar's own rule editor saved it). Heliostat has not overwritten it.\n"
            "Changes on disk since Heliostat loaded the file:"
        )
        intro.setWordWrap(True)
        diff = QPlainTextEdit(change.diff() or "(no difference in text)")
        diff.setReadOnly(True)
        diff.setFont(_fixed_font())
        diff.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        buttons = QDialogButtonBox()
        reload = QPushButton("Reload from disk" + (" (discard my edits)" if dirty else ""))
        overwrite = QPushButton("Overwrite with my version")
        buttons.addButton(reload, QDialogButtonBox.ButtonRole.DestructiveRole)
        buttons.addButton(overwrite, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        reload.clicked.connect(lambda: self._choose("reload"))
        overwrite.clicked.connect(lambda: self._choose("overwrite"))
        buttons.rejected.connect(self.reject)
        note = QLabel("Overwriting keeps a backup of the version on disk.")
        layout.addWidget(intro)
        layout.addWidget(diff, 1)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()
