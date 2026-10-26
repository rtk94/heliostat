# SPDX-License-Identifier: GPL-2.0-or-later
"""The main window: devices on the left, rules in the middle, the selected rule as a tree on the right,
problems at the bottom. Read-only.

The window opens from the rules file alone and lints it without device data; Solaar is read on a
thread pool (`read_solaar`), and the sidebar and problems update as its answers arrive.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtGui import QAction, QFontDatabase, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QMainWindow,
    QSplitter,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from heliostat.analysis import LintContext, Problem, Session, Severity, lint_ruleset, locations
from heliostat.analysis.lint import _parse_error
from heliostat.model import Raw, Rule, RuleSet
from heliostat.rulesfile import RulesParseError, loads
from heliostat.simple import not_simple_reason
from heliostat.solaar import SolaarClient
from heliostat.ui.solaar_state import SolaarState, read_solaar, status_lines
from heliostat.ui.tasks import Task
from heliostat.ui.text import Node, rule_nodes, rule_summary

PATH_ROLE = Qt.ItemDataRole.UserRole


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


class MainWindow(QMainWindow):
    """Emits solaarLoaded(SolaarState) once Solaar has been read and the problems updated."""

    solaarLoaded = Signal(object)

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
        self.lines: dict[tuple[int, ...], int] = {}
        if self.file.ruleset is not None:
            self.lines = locations(self.file.data, self.file.ruleset)
        elif self.file.parse_error is not None and self.file.parse_error.line is not None:
            self.lines[()] = self.file.parse_error.line
        self.solaar_state = SolaarState()
        self.context = LintContext(
            devices=None,
            devices_unavailable="Solaar has not answered yet",
            session=Session.from_env(self.env),
        )
        self.problems: list[Problem] = []
        self._tree_items: dict[tuple[int, ...], QTreeWidgetItem] = {}
        self._tasks: set[Task] = set()

        self.setWindowTitle(f"Heliostat — {rules_path}")
        self.resize(1300, 800)
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)
        self._build()
        self._show_file()
        self._relint()
        self.statusBar().showMessage(self._status_text())

    # Layout

    def _build(self) -> None:
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.banner.setMargin(8)
        self.banner.setStyleSheet("background: palette(highlight); color: palette(highlighted-text);")

        self.sidebar = DeviceSidebar()

        self.rule_list = QTreeWidget()
        self.rule_list.setHeaderLabels(["#", "Rule"])
        self.rule_list.setRootIsDecorated(False)
        self.rule_list.setUniformRowHeights(True)
        self.rule_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.rule_list.currentItemChanged.connect(self._on_rule_changed)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.rule_heading = QLabel("Select a rule")
        self.rule_heading.setWordWrap(True)
        self.rule_tree = QTreeWidget()
        self.rule_tree.setHeaderLabels(["Component", "Value"])
        self.rule_tree.setUniformRowHeights(True)
        right_layout.addWidget(self.rule_heading)
        right_layout.addWidget(self.rule_tree, 1)

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
        top.addWidget(self.rule_list)
        top.addWidget(right)
        top.setSizes([320, 580, 400])
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(top)
        main.addWidget(bottom)
        main.setSizes([560, 240])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addWidget(main, 1)
        self.setCentralWidget(central)

    # Solaar

    def start_solaar(self) -> None:
        """Read Solaar on the thread pool. The window is already usable."""
        task = Task(lambda report: read_solaar(self.client, report, self.env))
        task.signals.progress.connect(self._on_solaar_progress)
        task.signals.finished.connect(self._on_solaar_finished)
        task.signals.failed.connect(self._on_solaar_failed)
        self._tasks.add(task)
        task.signals.finished.connect(lambda _: self._tasks.discard(task))
        task.signals.failed.connect(lambda _: self._tasks.discard(task))
        self.pool.start(task)

    def _on_solaar_progress(self, state: SolaarState) -> None:
        self.solaar_state = state
        self.sidebar.show_state(state)
        self._refresh_rule_texts()

    def _on_solaar_finished(self, state: SolaarState) -> None:
        self._on_solaar_progress(state)
        self.context = state.context
        self._relint()
        self.statusBar().showMessage(self._status_text())
        self.solaarLoaded.emit(state)

    def _on_solaar_failed(self, details: str) -> None:
        self.sidebar.status.setText(f"Reading Solaar failed:\n{details.strip().splitlines()[-1]}")
        self.sidebar.status.setToolTip(details)

    # Rules file

    def _show_file(self) -> None:
        f = self.file
        if f.missing:
            self.banner.setText(f"No rules file at {f.path}. Solaar has no user rules.")
        elif f.read_error is not None:
            self.banner.setText(f"Cannot read {f.path}: {f.read_error}")
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
        mono = _fixed_font()
        for i, rule in enumerate(f.rules):
            item = QTreeWidgetItem([str(i + 1), ""])
            item.setData(0, PATH_ROLE, (i,))
            item.setTextAlignment(0, Qt.AlignmentFlag.AlignRight)
            if not_simple_reason(rule) is not None:
                item.setFont(1, mono)
            self.rule_list.addTopLevelItem(item)
        self._refresh_rule_texts()

    def _refresh_rule_texts(self) -> None:
        names = self.solaar_state.device_names
        for i, rule in enumerate(self.file.rules):
            item = self.rule_list.topLevelItem(i)
            text = rule_summary(rule, names)
            reason = not_simple_reason(rule)
            line = self.lines.get((i,))
            tip = [text, f"Line {line}" if line else "", "Simple rule" if reason is None else f"Advanced: {reason}"]
            item.setText(1, text)
            item.setToolTip(1, "\n".join(t for t in tip if t))
        self.rule_list.resizeColumnToContents(0)

    # Problems

    def _relint(self) -> None:
        if self.file.ruleset is not None:
            self.problems = lint_ruleset(self.file.ruleset, self.context)
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
        current = self.rule_list.currentItem()
        if current is not None:
            self._show_rule(current.data(0, PATH_ROLE)[0])

    def _where(self, problem: Problem) -> str:
        line = self.lines.get(problem.rule_path)
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
            self.rule_tree.clear()
            self._tree_items = {}
            self.rule_heading.setText("Select a rule")
            return
        self._show_rule(current.data(0, PATH_ROLE)[0])

    def _show_rule(self, index: int) -> None:
        rule = self.file.rules[index]
        reason = not_simple_reason(rule)
        line = self.lines.get((index,))
        heading = f"Rule {index + 1}" + (f" (line {line})" if line else "")
        heading += ": simple" if reason is None else f": advanced ({reason})"
        self.rule_heading.setText(heading)
        self.rule_tree.clear()
        self._tree_items = {}
        severities: dict[tuple[int, ...], list[Severity]] = {}
        for p in self.problems:
            if len(p.rule_path) > 1 and p.rule_path[0] == index:
                severities.setdefault(p.rule_path, []).append(p.severity)
        for node in rule_nodes(rule, index):
            self.rule_tree.addTopLevelItem(self._tree_item(node, severities))
        self.rule_tree.expandAll()
        self.rule_tree.resizeColumnToContents(0)

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
            _plural(n, word) for n, word in ((len(self.file.rules), "rule"), (errors, "error"), (warnings, "warning"))
        )
        if self.solaar_state.done:
            return text + f" (checked against Solaar {self.context.version_text})"
        return text + " (waiting for Solaar; checked against every supported Solaar version so far)"
