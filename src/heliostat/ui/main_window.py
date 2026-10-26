# SPDX-License-Identifier: GPL-2.0-or-later
"""The main window: devices on the left, rules in the middle, the selected rule on the right (the simple
form if it has the simple shape, and always the advanced tree), problems at the bottom.

The window opens from the rules file alone and lints it without device data; Solaar is read on a
thread pool (`read_solaar`), and the sidebar and problems update as its answers arrive.

Every edit goes through the RulesDocument's undo stack. Save writes with `rulesfile.save` (backup,
atomic replace, refusing to overwrite a file changed on disk); Apply saves, then asks Solaar to reload
the rules on the thread pool. Lint re-runs a moment after the last edit. A file that is not valid YAML,
or cannot be read, is shown but cannot be edited or saved.
"""

from __future__ import annotations

import copy
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QFontDatabase, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QStyle,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from heliostat.analysis import LintContext, Problem, Session, Severity, lint_ruleset, locations
from heliostat.analysis.lint import _parse_error
from heliostat.model import Raw, Rule, RuleSet, edit
from heliostat.rulesfile import (
    ExternalChange,
    RulesParseError,
    SaveResult,
    component_text,
    dumps,
    loads,
    rule_text,
    save,
)
from heliostat.simple import NotSimple, SimpleRule, generate, not_simple_reason, recognize
from heliostat.solaar import ReloadResult, SolaarClient
from heliostat.ui.dialogs import ExternalChangeDialog, SimpleRuleDialog, YamlDialog, parse_component, parse_rule
from heliostat.ui.document import RulePath, RulesDocument
from heliostat.ui.simple_editor import SimpleEditor
from heliostat.ui.solaar_state import SolaarState, read_solaar, status_lines
from heliostat.ui.tasks import Task
from heliostat.ui.text import Node, rule_nodes, rule_summary

PATH_ROLE = Qt.ItemDataRole.UserRole
LINT_DELAY_MS = 300  # lint this long after the last edit

# What the advanced editor's Add menu offers, as YAML in Solaar's saved shape, by group.
COMPONENT_TEMPLATES = {
    "Conditions": {
        "Key": "Key: [Back Button, pressed]",
        "MouseGesture": "MouseGesture: [Mouse Up]",
        "Modifiers": "Modifiers: [Shift, Control]",
        "Process": "Process: firefox",
        "MouseProcess": "MouseProcess: firefox",
        "Device": "Device: SERIAL",
        "Active": "Active: SERIAL",
        "Host": "Host: HOSTNAME",
        "Feature": "Feature: THUMB_WHEEL",
        "Report": "Report: 0",
        "Test": "Test: thumb_wheel_up",
        "TestBytes": "TestBytes: [0, 1, 1]",
        "KeyIsDown": "KeyIsDown: Back Button",
        "Setting": "Setting: [null, dpi, 1600]",
    },
    "Actions": {
        "KeyPress": "KeyPress:\n- Control_L\n- click",
        "MouseClick": "MouseClick: [left, 1]",
        "MouseScroll": "MouseScroll: [0, 1]",
        "Execute": "Execute: [notify-send, Heliostat]",
        "Set": "Set: [null, dpi, 1600]",
        "Later": "Later:\n- 1\n- KeyPress:\n  - Control_L\n  - click",
    },
    "Logic": {
        "Rule": "Rule: []",
        "Not": "Not:\n  Process: firefox",
        "Or": "Or: []",
        "And": "And: []",
    },
}


@dataclass
class RulesFile:
    """The rules file as read at startup. At most one of `ruleset`, `parse_error`, `read_error` is set;
    none of them when the file does not exist."""

    path: Path
    data: bytes | None = None
    ruleset: RuleSet | None = None
    parse_error: RulesParseError | None = None
    read_error: str | None = None

    @classmethod
    def read(cls, path: Path) -> RulesFile:
        if not path.exists():
            return cls(path)
        try:
            data = path.read_bytes()
        except OSError as e:
            return cls(path, read_error=e.strerror or str(e))
        try:
            return cls(path, data, ruleset=loads(data, path))
        except RulesParseError as e:
            return cls(path, data, parse_error=e)

    @property
    def editable(self) -> bool:
        """A file that parsed, or no file yet. Broken YAML and unreadable files are read-only."""
        return self.parse_error is None and self.read_error is None

    @property
    def missing(self) -> bool:
        return self.data is None and self.read_error is None

    @property
    def rules(self) -> list[Rule | Raw]:
        return self.ruleset.rules if self.ruleset is not None else []


def _severity_icon(widget: QWidget, severity: Severity | None):
    pixmap = {
        Severity.ERROR: QStyle.StandardPixmap.SP_MessageBoxCritical,
        Severity.WARNING: QStyle.StandardPixmap.SP_MessageBoxWarning,
        Severity.NOTE: QStyle.StandardPixmap.SP_MessageBoxInformation,
    }.get(severity)
    return widget.style().standardIcon(pixmap) if pixmap is not None else None


def _worst(severities: list[Severity]) -> Severity | None:
    return min(severities, key=lambda s: s.rank) if severities else None


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _fixed_font():
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)


class DeviceSidebar(QWidget):
    """Solaar's status and the devices it reports, with each online device's divertable controls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Device", "Status"])
        self.tree.setUniformRowHeights(True)
        layout.addWidget(self.status)
        layout.addWidget(self.tree, 1)
        self.show_state(SolaarState())

    def show_state(self, state: SolaarState) -> None:
        self.status.setText("\n".join(status_lines(state)))
        self.tree.clear()
        devices = sorted(state.devices or (), key=lambda d: not d.online)  # online first, otherwise as Solaar lists
        for device in devices:
            status = "online" if device.online else "offline"
            item = QTreeWidgetItem([device.name, f"{status}, {device.kind}" if device.kind else status])
            item.setToolTip(0, _device_tooltip(device))
            if not device.online:
                item.setDisabled(True)
            controls = [c for c in state.controls.get(device, ()) if c.divertable]
            for control in controls:
                mode = control.mode.value if control.mode is not None else "unknown"
                if control.saved_mode is not None and control.saved_mode is not control.mode:
                    mode += f" (saved: {control.saved_mode.value})"
                child = QTreeWidgetItem([control.name, mode])
                child.setToolTip(0, f"Modes: {', '.join(m.value for m in control.modes)}")
                item.addChild(child)
            if controls:
                diverted = sum(1 for c in controls if c.mode is not None and c.mode.diverted)
                item.setText(1, f"{item.text(1)}, {diverted} diverted")
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)


def _device_tooltip(device) -> str:
    lines = [device.name]
    for label, value in (("Codename", device.codename), ("Serial", device.serial), ("Unit ID", device.unit_id)):
        if value is not None:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _editor_devices(state: SolaarState) -> list[tuple[str, Any, list[tuple[str, str]]]]:
    """Online devices for the simple editor's pickers: (name, serial, [(divertable control, mode)])."""
    out = []
    for device in state.devices or ():
        if not device.online:
            continue
        controls = [
            (c.name, c.mode.value if c.mode is not None else "unknown")
            for c in state.controls.get(device, ())
            if c.divertable
        ]
        out.append((device.name, device.serial, controls))
    return out


class MainWindow(QMainWindow):
    """Emits solaarLoaded(SolaarState) once Solaar has been read and the problems updated,
    problemsUpdated() after each lint, saved(SaveResult) after a save, and applied(ReloadResult | str)
    when an Apply has finished (a str is the traceback of a reload that raised)."""

    solaarLoaded = Signal(object)
    problemsUpdated = Signal()
    saved = Signal(object)
    applied = Signal(object)

    def __init__(
        self,
        rules_path: Path,
        client: SolaarClient,
        pool: QThreadPool | None = None,
        env: Mapping[str, str] | None = None,
    ):
        super().__init__()
        self.env = os.environ if env is None else env
        self.client = client
        self.pool = pool if pool is not None else QThreadPool.globalInstance()
        self.file = RulesFile.read(rules_path)
        self.document = RulesDocument(copy.deepcopy(self.file.ruleset) or RuleSet(), self)
        self.document.changed.connect(self._on_document_changed)
        self.document.undo_stack.cleanChanged.connect(self._on_clean_changed)
        self.lines: dict[tuple[int, ...], int] = {}
        self._compute_lines()
        self.solaar_state = SolaarState()
        self.context = LintContext(
            devices=None,
            devices_unavailable="Solaar has not answered yet",
            session=Session.from_env(self.env),
        )
        self.problems: list[Problem] = []
        self._tree_items: dict[tuple[int, ...], QTreeWidgetItem] = {}
        self._tasks: set[Task] = set()
        self._applying = False
        self._lint_timer = QTimer(self)
        self._lint_timer.setSingleShot(True)
        self._lint_timer.setInterval(LINT_DELAY_MS)
        self._lint_timer.timeout.connect(self._relint)

        self.setWindowTitle(f"Heliostat — {rules_path}[*]")
        self.resize(1400, 860)
        self._build()
        self._build_actions()
        self._show_file()
        self._relint()
        self._update_actions()

    @property
    def rules(self) -> list[Rule | Raw]:
        return self.document.ruleset.rules

    @property
    def editable(self) -> bool:
        return self.file.editable

    @property
    def dirty(self) -> bool:
        return not self.document.undo_stack.isClean()

    def _compute_lines(self) -> None:
        """Line numbers in the file on disk, for the rules as loaded or last saved."""
        self.lines = {}
        if self.file.ruleset is not None and self.file.data is not None:
            self.lines = locations(self.file.data, self.file.ruleset)
        elif self.file.parse_error is not None and self.file.parse_error.line is not None:
            self.lines[()] = self.file.parse_error.line

    def _line(self, path: tuple[int, ...]) -> int | None:
        """The line of a rule path in the file on disk; None once the rules are edited and unsaved."""
        return None if self.dirty else self.lines.get(path)

    # Layout

    def _build(self) -> None:
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.banner.setMargin(8)
        self.banner.setStyleSheet("background: palette(highlight); color: palette(highlighted-text);")

        self.sidebar = DeviceSidebar()

        rules_pane = QWidget()
        rules_layout = QVBoxLayout(rules_pane)
        rules_layout.setContentsMargins(0, 0, 0, 0)
        self.rule_list = QTreeWidget()
        self.rule_list.setHeaderLabels(["#", "Rule"])
        self.rule_list.setRootIsDecorated(False)
        self.rule_list.setUniformRowHeights(True)
        self.rule_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.rule_list.currentItemChanged.connect(self._on_rule_changed)
        self.rule_buttons = QHBoxLayout()
        rules_layout.addWidget(self.rule_list, 1)
        rules_layout.addLayout(self.rule_buttons)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.rule_heading = QLabel("Select a rule")
        self.rule_heading.setWordWrap(True)
        self.simple_editor = SimpleEditor()
        self.simple_editor.edited.connect(self._on_simple_edited)
        simple_scroll = QScrollArea()
        simple_scroll.setWidgetResizable(True)
        simple_scroll.setWidget(self.simple_editor)
        advanced = QWidget()
        advanced_layout = QVBoxLayout(advanced)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        self.rule_tree = QTreeWidget()
        self.rule_tree.setHeaderLabels(["Component", "Value"])
        self.rule_tree.setUniformRowHeights(True)
        self.rule_tree.currentItemChanged.connect(lambda *_: self._update_actions())
        self.rule_tree.itemDoubleClicked.connect(lambda *_: self.edit_component())
        self.tree_buttons = QHBoxLayout()
        advanced_layout.addWidget(self.rule_tree, 1)
        advanced_layout.addLayout(self.tree_buttons)
        self.editor_tabs = QTabWidget()
        self.simple_tab = self.editor_tabs.addTab(simple_scroll, "Simple")
        self.advanced_tab = self.editor_tabs.addTab(advanced, "Advanced")
        right_layout.addWidget(self.rule_heading)
        right_layout.addWidget(self.editor_tabs, 1)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.problem_list = QTreeWidget()
        self.problem_list.setHeaderLabels(["Severity", "Code", "Where", "Message"])
        self.problem_list.setRootIsDecorated(False)
        self.problem_list.setUniformRowHeights(True)
        self.problem_list.currentItemChanged.connect(self._on_problem_changed)
        self.problem_detail = QLabel()
        self.problem_detail.setWordWrap(True)
        self.problem_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bottom_layout.addWidget(self.problem_list, 1)
        bottom_layout.addWidget(self.problem_detail)

        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self.sidebar)
        top.addWidget(rules_pane)
        top.addWidget(right)
        top.setSizes([300, 560, 540])
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top)
        main.addWidget(bottom)
        main.setSizes([600, 220])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addWidget(main, 1)
        self.setCentralWidget(central)

        self.save_result = QLabel()
        self.save_result.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.statusBar().addPermanentWidget(self.save_result)

    def _action(self, text: str, slot: Callable, shortcut=None, widget: QWidget | None = None, tip="") -> QAction:
        """An action; with `widget`, its shortcut only works while focus is in that widget."""
        action = QAction(text, self)
        action.triggered.connect(lambda: slot())
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        if widget is not None:
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            widget.addAction(action)
        else:
            self.addAction(action)
        return action

    def _button(self, layout: QHBoxLayout, action: QAction | None = None, text="", menu: QMenu | None = None):
        button = QToolButton()
        if action is not None:
            button.setDefaultAction(action)
        else:
            button.setText(text)
            button.setMenu(menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        layout.addWidget(button)
        return button

    def _build_actions(self) -> None:
        stack = self.document.undo_stack
        self.undo_action = stack.createUndoAction(self, "Undo")
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action = stack.createRedoAction(self, "Redo")
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.addActions([self.undo_action, self.redo_action])
        self.save_action = self._action("Save", self.save, QKeySequence.StandardKey.Save, tip="Write rules.yaml")
        self.apply_action = self._action(
            "Apply", self.apply, "Ctrl+Return", tip="Save, then get Solaar to load the rules (restarts Solaar)"
        )
        self.reload_action = self._action("Reload from disk", self.reload_from_disk, tip="Discard edits, read the file")
        quit_action = self._action("Quit", self.close, QKeySequence.StandardKey.Quit)

        rl = self.rule_list
        self.new_rule_action = self._action("New rule…", self.new_simple_rule, "Ctrl+N")
        self.new_advanced_rule_action = self._action("New empty advanced rule", self.new_advanced_rule)
        self.duplicate_rule_action = self._action("Duplicate", self.duplicate_rule, "Ctrl+D", rl)
        self.delete_rule_action = self._action("Delete", self.delete_rule, QKeySequence.StandardKey.Delete, rl)
        self.rule_up_action = self._action("Move up", lambda: self.move_rule(-1), "Alt+Up", rl)
        self.rule_down_action = self._action("Move down", lambda: self.move_rule(1), "Alt+Down", rl)
        self.edit_rule_yaml_action = self._action("Edit as YAML…", self.edit_rule_yaml, "Ctrl+E", rl)

        tree = self.rule_tree
        self.add_after_menu = self._templates_menu(lambda t: self.add_component(t, inside=False))
        self.add_inside_menu = self._templates_menu(lambda t: self.add_component(t, inside=True))
        self.edit_component_action = self._action("Edit…", self.edit_component, "Return", tree)
        self.remove_component_action = self._action(
            "Remove", self.remove_component, QKeySequence.StandardKey.Delete, tree
        )
        self.component_up_action = self._action("Move up", lambda: self.move_component(-1), "Alt+Up", tree)
        self.component_down_action = self._action("Move down", lambda: self.move_component(1), "Alt+Down", tree)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions([self.save_action, self.apply_action, self.reload_action])
        file_menu.addSeparator()
        file_menu.addAction(quit_action)
        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addActions([self.undo_action, self.redo_action])
        rule_menu = self.menuBar().addMenu("&Rule")
        rule_menu.addActions(
            [
                self.new_rule_action,
                self.new_advanced_rule_action,
                self.duplicate_rule_action,
                self.delete_rule_action,
                self.rule_up_action,
                self.rule_down_action,
                self.edit_rule_yaml_action,
            ]
        )

        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("main-toolbar")
        toolbar.addActions([self.save_action, self.apply_action])
        toolbar.addSeparator()
        toolbar.addActions([self.undo_action, self.redo_action])

        new_menu = QMenu(self)
        new_menu.addActions([self.new_rule_action, self.new_advanced_rule_action])
        self._button(self.rule_buttons, text="New", menu=new_menu)
        for action in (
            self.duplicate_rule_action,
            self.delete_rule_action,
            self.rule_up_action,
            self.rule_down_action,
            self.edit_rule_yaml_action,
        ):
            self._button(self.rule_buttons, action)
        self.rule_buttons.addStretch(1)

        self.add_after_button = self._button(self.tree_buttons, text="Add", menu=self.add_after_menu)
        self.add_after_button.setToolTip("Add a component after the selected one (or at the end of the rule)")
        self.add_inside_button = self._button(self.tree_buttons, text="Add inside", menu=self.add_inside_menu)
        self.add_inside_button.setToolTip("Add a component at the end of the selected Rule, Or, And or Later")
        for action in (
            self.edit_component_action,
            self.remove_component_action,
            self.component_up_action,
            self.component_down_action,
        ):
            self._button(self.tree_buttons, action)
        self.tree_buttons.addStretch(1)

    def _templates_menu(self, slot: Callable[[str], None]) -> QMenu:
        menu = QMenu(self)
        for group, templates in COMPONENT_TEMPLATES.items():
            sub = menu.addMenu(group)
            for name, template in templates.items():
                sub.addAction(name, lambda template=template: slot(template))
        return menu

    def _update_actions(self) -> None:
        editable = self.editable
        index = self.current_index()
        has_rule = index is not None
        for action in (self.save_action, self.apply_action, self.new_rule_action, self.new_advanced_rule_action):
            action.setEnabled(editable)
        self.reload_action.setEnabled(not self.file.missing or self.dirty)
        self.duplicate_rule_action.setEnabled(editable and has_rule)
        self.delete_rule_action.setEnabled(editable and has_rule)
        self.edit_rule_yaml_action.setEnabled(editable and has_rule)
        ruleset = self.document.ruleset
        self.rule_up_action.setEnabled(editable and has_rule and edit.can_move(ruleset, (index,), -1))
        self.rule_down_action.setEnabled(editable and has_rule and edit.can_move(ruleset, (index,), 1))
        path = self.current_component_path()
        in_rule = editable and has_rule and isinstance(self.rules[index], Rule)
        self.add_after_button.setEnabled(in_rule and (path is None or self._can_add_after(path)))
        self.add_inside_button.setEnabled(
            in_rule and path is not None and edit.children(edit.get(ruleset, path)) is not None
        )
        self.edit_component_action.setEnabled(editable and path is not None)
        self.remove_component_action.setEnabled(editable and path is not None and edit.can_remove(ruleset, path))
        self.component_up_action.setEnabled(editable and path is not None and edit.can_move(ruleset, path, -1))
        self.component_down_action.setEnabled(editable and path is not None and edit.can_move(ruleset, path, 1))
        self.simple_editor.setEnabled(editable)

    def _can_add_after(self, path: RulePath) -> bool:
        if len(path) < 2:
            return False
        return edit.children(edit.get(self.document.ruleset, path[:-1])) is not None or len(path) == 2

    # Solaar

    def start_solaar(self) -> None:
        """Read Solaar on the thread pool. The window is already usable."""
        self._run(
            lambda report: read_solaar(self.client, report, self.env),
            self._on_solaar_finished,
            self._on_solaar_failed,
            self._on_solaar_progress,
        )

    def _run(self, work, finished, failed, progress=None) -> None:
        task = Task(work)
        if progress is not None:
            task.signals.progress.connect(progress)
        task.signals.finished.connect(finished)
        task.signals.failed.connect(failed)
        self._tasks.add(task)
        task.signals.finished.connect(lambda _: self._tasks.discard(task))
        task.signals.failed.connect(lambda _: self._tasks.discard(task))
        self.pool.start(task)

    def _on_solaar_progress(self, state: SolaarState) -> None:
        self.solaar_state = state
        self.sidebar.show_state(state)
        self.simple_editor.set_devices(_editor_devices(state), state.device_names)
        self._refresh_rule_texts()

    def _on_solaar_finished(self, state: SolaarState) -> None:
        self._on_solaar_progress(state)
        self.context = state.context
        self._relint()
        self.solaarLoaded.emit(state)

    def _on_solaar_failed(self, details: str) -> None:
        self.sidebar.status.setText(f"Reading Solaar failed:\n{details.strip().splitlines()[-1]}")
        self.sidebar.status.setToolTip(details)

    # Rules file

    def _show_file(self) -> None:
        f = self.file
        self.banner.show()
        if f.missing:
            self.banner.setText(f"No rules file at {f.path}. Solaar has no user rules. Saving creates the file.")
        elif f.read_error is not None:
            self.banner.setText(f"Cannot read {f.path}: {f.read_error}. Heliostat will not edit or save it.")
        elif f.parse_error is not None:
            e = f.parse_error
            where = f"line {e.line}, column {e.column}" if e.line is not None else "an unknown position"
            self.banner.setText(
                f"{f.path} is not valid YAML ({where}: {e.message}). Solaar is running only the "
                f"{e.documents_parsed} rule(s) before the error, and its next save of the rules drops the rest. "
                "Heliostat will not edit this file until the error is fixed."
            )
        else:
            self.banner.hide()
        self._rebuild_rule_list(None)

    def _rebuild_rule_list(self, select: int | None) -> None:
        """Fill the rule list from the document and select rule `select` (None keeps the current row)."""
        if select is None:
            select = self.current_index()
        self.rule_list.blockSignals(True)
        try:
            self.rule_list.clear()
            mono = _fixed_font()
            for i, rule in enumerate(self.rules):
                item = QTreeWidgetItem([str(i + 1), ""])
                item.setData(0, PATH_ROLE, (i,))
                item.setTextAlignment(0, Qt.AlignmentFlag.AlignRight)
                if not_simple_reason(rule) is not None:
                    item.setFont(1, mono)
                self.rule_list.addTopLevelItem(item)
            if select is not None and self.rules:
                self.rule_list.setCurrentItem(self.rule_list.topLevelItem(min(select, len(self.rules) - 1)))
        finally:
            self.rule_list.blockSignals(False)
        self._refresh_rule_texts()
        self._show_problem_icons()

    def _refresh_rule_texts(self) -> None:
        names = self.solaar_state.device_names
        for i, rule in enumerate(self.rules):
            item = self.rule_list.topLevelItem(i)
            text = rule_summary(rule, names)
            reason = not_simple_reason(rule)
            line = self._line((i,))
            tip = [text, f"Line {line}" if line else "", "Simple rule" if reason is None else f"Advanced: {reason}"]
            item.setText(1, text)
            item.setToolTip(1, "\n".join(t for t in tip if t))
        self.rule_list.resizeColumnToContents(0)

    def current_index(self) -> int | None:
        item = self.rule_list.currentItem()
        return item.data(0, PATH_ROLE)[0] if item is not None else None

    def current_component_path(self) -> RulePath | None:
        """The rule path of the component selected in the advanced tree."""
        item = self.rule_tree.currentItem()
        return item.data(0, PATH_ROLE) if item is not None else None

    # Editing

    def _on_document_changed(self, select: RulePath | None, source: Any) -> None:
        index = select[0] if select else self.current_index()
        tree_path = select if select is not None and len(select) > 1 else self.current_component_path()
        self._rebuild_rule_list(index)
        current = self.current_index()
        if current is None:
            self._clear_rule()
        else:
            self._show_rule(current, tree_path, reload_simple=source is not self.simple_editor)
        self._lint_timer.start()
        self._update_actions()

    def _on_clean_changed(self, clean: bool) -> None:
        """Line numbers are shown only while the rules match the file on disk."""
        self.setWindowModified(not clean)
        self._refresh_rule_texts()
        index = self.current_index()
        if index is not None:
            self._show_heading(index)
        for row, problem in enumerate(self.problems):
            self.problem_list.topLevelItem(row).setText(2, self._where(problem))
        self._update_actions()

    def _edit(self, label: str, after: RuleSet, select: RulePath | None, **kwargs) -> bool:
        index = self.current_index()
        before = self.current_component_path() or ((index,) if index is not None else None)
        return self.document.edit(label, after, select, select_before=before, **kwargs)

    def _on_simple_edited(self, simple: SimpleRule, merge_key: str | None) -> None:
        index = self.current_index()
        if index is None or not self.editable:
            return
        try:
            rule = generate(simple)
        except NotSimple:
            return  # incomplete (e.g. a gesture with no movements yet); the form says what is missing
        after = edit.replace(self.document.ruleset, (index,), rule)
        key = (index, merge_key) if merge_key is not None else None
        self._edit(f"Edit rule {index + 1}", after, (index,), merge_key=key, source=self.simple_editor)

    def insert_rule(self, rule: Rule | Raw, label: str = "Add rule") -> None:
        """Insert after the selected rule, or at the end."""
        index = self.current_index()
        position = len(self.rules) if index is None else index + 1
        self._edit(label, edit.insert(self.document.ruleset, (position,), rule), (position,))

    def new_simple_rule(self) -> None:
        rule = self.ask_new_rule()
        if rule is not None:
            self.insert_rule(rule)
            self.editor_tabs.setCurrentIndex(self.simple_tab)

    def new_advanced_rule(self) -> None:
        self.insert_rule(Rule([]), "Add empty rule")
        self.editor_tabs.setCurrentIndex(self.advanced_tab)

    def duplicate_rule(self) -> None:
        index = self.current_index()
        if index is not None:
            after = edit.insert(self.document.ruleset, (index + 1,), self.rules[index])
            self._edit(f"Duplicate rule {index + 1}", after, (index + 1,))

    def delete_rule(self) -> None:
        index = self.current_index()
        if index is not None:
            after = edit.remove(self.document.ruleset, (index,))
            self._edit(f"Delete rule {index + 1}", after, (min(index, len(after.rules) - 1),) if after.rules else None)

    def move_rule(self, delta: int) -> None:
        index = self.current_index()
        if index is not None and edit.can_move(self.document.ruleset, (index,), delta):
            after, path = edit.move(self.document.ruleset, (index,), delta)
            self._edit(f"Move rule {index + 1}", after, path)

    def edit_rule_yaml(self) -> None:
        index = self.current_index()
        if index is None:
            return
        rule = self.ask_yaml(f"Rule {index + 1} as YAML", rule_text(self.rules[index]), parse_rule)
        if rule is not None:
            self._edit(f"Edit rule {index + 1}", edit.replace(self.document.ruleset, (index,), rule), (index,))

    def add_component(self, template: str, inside: bool) -> None:
        index = self.current_index()
        if index is None or not isinstance(self.rules[index], Rule):
            return
        path = self.current_component_path()
        if inside and path is not None:
            position = (*path, len(edit.children(edit.get(self.document.ruleset, path))))
        elif path is not None and len(path) > 1 and self._can_add_after(path):
            position = (*path[:-1], path[-1] + 1)
        else:
            position = (index, len(self.rules[index].components))
        component = self.ask_yaml("New component", template + "\n", parse_component)
        if component is not None:
            after = edit.insert(self.document.ruleset, position, component)
            self._edit(f"Add {_type_label(component)}", after, position)

    def edit_component(self) -> None:
        path = self.current_component_path()
        if path is None or not self.editable:
            return
        if len(path) == 1:
            self.edit_rule_yaml()
            return
        component = edit.get(self.document.ruleset, path)
        new = self.ask_yaml(f"Edit {_type_label(component)}", component_text(component), parse_component)
        if new is not None:
            self._edit(f"Edit {_type_label(component)}", edit.replace(self.document.ruleset, path, new), path)

    def remove_component(self) -> None:
        path = self.current_component_path()
        if path is None or len(path) < 2 or not edit.can_remove(self.document.ruleset, path):
            return
        component = edit.get(self.document.ruleset, path)
        after = edit.remove(self.document.ruleset, path)
        parent = path[:-1]
        remaining = len(edit.children(edit.get(after, parent)))
        select = (*parent, min(path[-1], remaining - 1)) if remaining else parent
        self._edit(f"Remove {_type_label(component)}", after, select)

    def move_component(self, delta: int) -> None:
        path = self.current_component_path()
        if path is None or len(path) < 2 or not edit.can_move(self.document.ruleset, path, delta):
            return
        component = edit.get(self.document.ruleset, path)
        after, new_path = edit.move(self.document.ruleset, path, delta)
        self._edit(f"Move {_type_label(component)}", after, new_path)

    # Save and apply

    def save(self) -> bool:
        """Write the rules. True if the file on disk now holds them."""
        if not self.editable:
            return False
        overwrite = False
        while True:
            try:
                result = save(self.file.path, dumps(self.document.ruleset), self.file.data, overwrite=overwrite)
            except ExternalChange as change:
                choice = self.ask_external_change(change)
                if choice == "overwrite":
                    overwrite = True
                    continue
                if choice == "reload":
                    self._reload()
                self.save_result.setText("Not saved: the file changed on disk")
                return False
            except OSError as e:
                self.show_error("Could not save the rules", f"{self.file.path}: {e.strerror or e}")
                self.save_result.setText("Save failed")
                return False
            break
        self._saved(result)
        return True

    def _saved(self, result: SaveResult) -> None:
        self.file = RulesFile(self.file.path, result.data, ruleset=copy.deepcopy(self.document.ruleset))
        self._compute_lines()
        self.document.undo_stack.setClean()
        self.banner.hide()
        if result.written:
            text = f"Saved {result.path}" + (f"; backup {result.backup.name}" if result.backup else "")
        else:
            text = "No changes to save"
        self.save_result.setText(text)
        self.save_result.setToolTip(str(result.path))
        self._refresh_rule_texts()
        self._update_actions()
        self.saved.emit(result)

    def apply(self) -> None:
        """Save, then get Solaar to load the rules (on the thread pool; it restarts Solaar)."""
        if self._applying or not self.save():
            return
        self._applying = True
        self.apply_action.setEnabled(False)
        self.save_result.setText(self.save_result.text() + "; getting Solaar to load the rules…")
        self._run(lambda _report: self.client.reload_rules(), self._on_applied, self._on_apply_failed)

    def _on_applied(self, result: ReloadResult) -> None:
        self._applying = False
        self._update_actions()
        if result.ok:
            self.save_result.setText(f"Applied: {result.message}")
        else:
            self.save_result.setText(f"Saved, but Solaar has not loaded the rules: {result.message}")
        self.save_result.setToolTip(str(result))
        if not result.ok:
            self.show_error("Solaar did not load the rules", str(result))
        self.applied.emit(result)

    def _on_apply_failed(self, details: str) -> None:
        self._applying = False
        self._update_actions()
        last = details.strip().splitlines()[-1]
        self.save_result.setText(f"Saved, but reloading Solaar failed: {last}")
        self.save_result.setToolTip(details)
        self.show_error("Reloading Solaar failed", details)
        self.applied.emit(details)

    def reload_from_disk(self) -> None:
        if self.dirty and not self.ask_discard():
            return
        self._reload()

    def _reload(self) -> None:
        self.file = RulesFile.read(self.file.path)
        self._compute_lines()
        self.document.reset(copy.deepcopy(self.file.ruleset) or RuleSet())
        self._show_file()
        self.save_result.setText("Reloaded from disk")

    def closeEvent(self, event) -> None:
        if self.dirty and self.editable:
            choice = self.ask_unsaved()
            if choice == "cancel" or (choice == "save" and not self.save()):
                event.ignore()
                return
        event.accept()

    # Questions for the user. Tests replace these.

    def ask_external_change(self, change: ExternalChange) -> str:
        """ "reload", "overwrite" or "cancel"."""
        dialog = ExternalChangeDialog(self, change, self.dirty)
        return dialog.choice if dialog.exec() == QDialog.DialogCode.Accepted else "cancel"

    def ask_unsaved(self) -> str:
        """ "save", "discard" or "cancel"."""
        buttons = QMessageBox.StandardButton
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "Save the changes to the rules before closing?",
            buttons.Save | buttons.Discard | buttons.Cancel,
            buttons.Save,
        )
        return {buttons.Save: "save", buttons.Discard: "discard"}.get(answer, "cancel")

    def ask_discard(self) -> bool:
        buttons = QMessageBox.StandardButton
        answer = QMessageBox.question(
            self,
            "Discard changes?",
            "Discard your unsaved changes and read the file again?",
            buttons.Discard | buttons.Cancel,
        )
        return answer == buttons.Discard

    def ask_new_rule(self) -> Rule | None:
        dialog = SimpleRuleDialog(self, _editor_devices(self.solaar_state), self.solaar_state.device_names)
        return dialog.rule if dialog.exec() == QDialog.DialogCode.Accepted else None

    def ask_yaml(self, title: str, text: str, parse: Callable[[str], tuple[Any, str]]) -> Any:
        """The value `parse` made of the text the user accepted, or None if cancelled."""
        dialog = YamlDialog(self, title, text, parse)
        return dialog.value if dialog.exec() == QDialog.DialogCode.Accepted else None

    def show_error(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)

    # Problems

    def _relint(self) -> None:
        self._lint_timer.stop()
        if self.editable:
            self.problems = lint_ruleset(self.document.ruleset, self.context)
        elif self.file.parse_error is not None:
            self.problems = [_parse_error(self.file.parse_error)]
        else:
            self.problems = []
        self.problem_list.clear()
        self.problem_detail.clear()
        for problem in self.problems:
            item = QTreeWidgetItem([problem.severity.value, problem.code, self._where(problem), problem.message])
            item.setIcon(0, _severity_icon(self, problem.severity))
            item.setData(0, PATH_ROLE, problem.rule_path)
            item.setToolTip(3, self._problem_text(problem))
            self.problem_list.addTopLevelItem(item)
        for column in range(3):
            self.problem_list.resizeColumnToContents(column)
        self._show_problem_icons()
        current = self.current_index()
        if current is not None:
            self._show_tree(current, self.current_component_path())
        self.statusBar().showMessage(self._status_text())
        self.problemsUpdated.emit()

    def _show_problem_icons(self) -> None:
        by_rule: dict[int, list[Severity]] = {}
        for p in self.problems:
            if p.rule_path and p.severity is not Severity.NOTE:
                by_rule.setdefault(p.rule_path[0], []).append(p.severity)
        for i in range(self.rule_list.topLevelItemCount()):
            icon = _severity_icon(self, _worst(by_rule.get(i, [])))
            item = self.rule_list.topLevelItem(i)
            if icon is not None:
                item.setIcon(0, icon)
            else:
                item.setData(0, Qt.ItemDataRole.DecorationRole, None)

    def _where(self, problem: Problem) -> str:
        line = self._line(problem.rule_path)
        parts = [f"rule {problem.rule_path[0] + 1}"] if problem.rule_path else []
        if line:
            parts.append(f"line {line}")
        return ", ".join(parts) or "file"

    def _problem_text(self, problem: Problem) -> str:
        text = f"{problem.code} {problem.name}: {problem.message}" if problem.code else problem.message
        if problem.fix is not None:
            text += f"\nFix: {problem.fix.description}"
            if problem.fix.command:
                text += "\nRun: " + " ".join(problem.fix.command)
        return text

    # Selection

    def _on_rule_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            self._clear_rule()
        else:
            index = current.data(0, PATH_ROLE)[0]
            self._show_rule(index)
            simple = not_simple_reason(self.rules[index]) is None
            self.editor_tabs.setCurrentIndex(self.simple_tab if simple else self.advanced_tab)
        self._update_actions()

    def _clear_rule(self) -> None:
        self.rule_tree.clear()
        self._tree_items = {}
        self.rule_heading.setText("Select a rule")
        self.editor_tabs.setTabEnabled(self.simple_tab, False)
        self.editor_tabs.setCurrentIndex(self.advanced_tab)

    def _show_heading(self, index: int) -> None:
        reason = not_simple_reason(self.rules[index])
        line = self._line((index,))
        heading = f"Rule {index + 1}" + (f" (line {line})" if line else "")
        heading += ": simple" if reason is None else f": advanced ({reason})"
        self.rule_heading.setText(heading)

    def _show_rule(self, index: int, tree_path: RulePath | None = None, reload_simple: bool = True) -> None:
        rule = self.rules[index]
        reason = not_simple_reason(rule)
        self._show_heading(index)
        self._show_tree(index, tree_path)
        simple = recognize(rule) if reason is None else None
        self.editor_tabs.setTabEnabled(self.simple_tab, simple is not None)
        self.editor_tabs.setTabToolTip(self.simple_tab, "" if simple is not None else f"Not a simple rule: {reason}")
        if simple is None:
            self.editor_tabs.setCurrentIndex(self.advanced_tab)
        elif reload_simple:
            self.simple_editor.set_rule(simple)

    def _show_tree(self, index: int, select: RulePath | None = None) -> None:
        self.rule_tree.blockSignals(True)
        try:
            self.rule_tree.clear()
            self._tree_items = {}
            severities: dict[tuple[int, ...], list[Severity]] = {}
            for p in self.problems:
                if len(p.rule_path) > 1 and p.rule_path[0] == index:
                    severities.setdefault(p.rule_path, []).append(p.severity)
            for node in rule_nodes(self.rules[index], index):
                self.rule_tree.addTopLevelItem(self._tree_item(node, severities))
            self.rule_tree.expandAll()
            self.rule_tree.resizeColumnToContents(0)
            item = self._tree_items.get(select) if select is not None and select[0] == index else None
            if item is not None:
                self.rule_tree.setCurrentItem(item)
        finally:
            self.rule_tree.blockSignals(False)
        self._update_actions()

    def _tree_item(self, node: Node, severities) -> QTreeWidgetItem:
        item = QTreeWidgetItem([node.label, node.value])
        item.setData(0, PATH_ROLE, node.path)
        item.setFont(1, _fixed_font())
        if node.tooltip:
            item.setToolTip(0, node.tooltip)
            item.setToolTip(1, node.tooltip)
        if node.unrecognized:
            font = item.font(0)
            font.setItalic(True)
            item.setFont(0, font)
        icon = _severity_icon(self, _worst(severities.get(node.path, [])))
        if icon is not None:
            item.setIcon(0, icon)
        self._tree_items[node.path] = item
        for child in node.children:
            item.addChild(self._tree_item(child, severities))
        return item

    def _on_problem_changed(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            self.problem_detail.clear()
            return
        index = self.problem_list.indexOfTopLevelItem(current)
        self.problem_detail.setText(self._problem_text(self.problems[index]))
        self.select_path(current.data(0, PATH_ROLE))

    def select_path(self, path: tuple[int, ...]) -> None:
        """Select the rule a problem is in and, if it points inside the rule, that component in the tree."""
        if not path or path[0] >= self.rule_list.topLevelItemCount():
            return
        self.rule_list.setCurrentItem(self.rule_list.topLevelItem(path[0]))
        self.rule_list.scrollToItem(self.rule_list.currentItem())
        item = self._tree_items.get(path)
        if item is not None:
            self.rule_tree.setCurrentItem(item)
            self.rule_tree.scrollToItem(item)
        else:
            self.rule_tree.clearSelection()

    def _status_text(self) -> str:
        errors = sum(p.severity is Severity.ERROR for p in self.problems)
        warnings = sum(p.severity is Severity.WARNING for p in self.problems)
        text = ", ".join(
            _plural(n, word) for n, word in ((len(self.rules), "rule"), (errors, "error"), (warnings, "warning"))
        )
        if self.solaar_state.done:
            return text + f" (checked against Solaar {self.context.version_text})"
        return text + " (waiting for Solaar; checked against every supported Solaar version so far)"


def _type_label(component) -> str:
    if isinstance(component, Raw):
        return component.type_name or "component"
    return component.TYPE
