# SPDX-License-Identifier: GPL-2.0-or-later
"""The plain-language form for a simple rule: trigger, optional device, modifiers and program, actions.

The form edits a SimpleRule. Every change the user makes emits `edited(simple, merge_key)` with the
rule as the form now shows it; text typed into a field carries a merge key (the field), so a word
typed is one undo step. Fields left alone keep the components they were loaded from (SimpleRule's
`written`, and the action components themselves); an action the user edits is rebuilt in Solaar's
saved shape, like a condition (docs/decisions.md, Phase 4 and 6).

Nothing here touches the RuleSet; the window turns `edited` into an undoable edit.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import yaml
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from heliostat.model import (
    CLICK,
    CLICK_ACTIONS,
    DEPRESS,
    PRESSED,
    RELEASE,
    RELEASED,
    Component,
    Execute,
    KeyPress,
    MouseClick,
    MouseScroll,
    Set,
)
from heliostat.simple import GestureTrigger, KeyTrigger, NotSimple, SimpleRule, describe, describe_action, generate
from heliostat.solaar.names import MOVEMENTS

# Solaar's modifier names (diversion.MODIFIERS), with the labels shown for them.
MODIFIERS = (("Shift", "Shift"), ("Control", "Ctrl"), ("Alt", "Alt"), ("Super", "Super"))
# Solaar's MouseClick button names (diversion.buttons, without "unknown").
BUTTONS = ("left", "middle", "right", "scroll_up", "scroll_down", "scroll_left", "scroll_right", "button8", "button9")
_MOVEMENT_NAMES = tuple(dict.fromkeys(name for names in MOVEMENTS.values() for name in names))

PRESS, RELEASE_TRIGGER, GESTURE = "pressed", "released", "gesture"
_TRIGGER_KINDS = ((PRESS, "Button is pressed"), (RELEASE_TRIGGER, "Button is released"), (GESTURE, "Mouse gesture"))

# Actions the Add menu creates, in Solaar's saved shape: (label, factory).
NEW_ACTIONS = (
    ("Press keys", lambda: KeyPress(["Control_L", "c"], CLICK)),
    ("Click a mouse button", lambda: MouseClick("left", 1)),
    ("Scroll", lambda: MouseScroll(0, 1)),
    ("Run a command", lambda: Execute(["notify-send", "Heliostat"])),
    ("Change a device setting", lambda: Set(None, "dpi", [1600])),
)

_KEY_ACTIONS = ((CLICK, "press and release"), (DEPRESS, "hold down"), (RELEASE, "release"))


class Invalid(ValueError):
    """A field holds something that cannot be written yet."""


def _set_combo_text(combo: QComboBox, text: str) -> None:
    index = combo.findText(text, Qt.MatchFlag.MatchExactly)
    if index >= 0:
        combo.setCurrentIndex(index)
    combo.setEditText(text)


def _scalar(text: str) -> Any:
    """A YAML scalar typed into a field (1600, true, Smart Shift)."""
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise Invalid(f"{text!r} is not a value") from e
    if not (value is None or isinstance(value, (str, int, float))):
        raise Invalid(f"{text!r} is not a single value")
    return value


def _number(text: str, what: str) -> int | float:
    value = _scalar(text.strip() or "0")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Invalid(f"{what} must be a number")
    return value


def _show(value: Any) -> str:
    if value is None:
        return ""
    return yaml.safe_dump(value, default_flow_style=True).removesuffix("\n...\n").strip()


class ActionEditor(QStackedWidget):
    """Fields for one action. `changed` fires when the user edits one; `action()` builds the component."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._kind: type[Component] | None = None
        self.addWidget(QLabel("Select an action to edit it."))

        page, form = self._page()
        self.keys = self._line(form, "Keys", "X key names separated by spaces, e.g. Control_L Tab")
        self.key_action = self._combo(form, "Action", _KEY_ACTIONS)
        self._pages = {KeyPress: page}

        page, form = self._page()
        self.button = QComboBox()
        self.button.setEditable(True)
        self.button.addItems(BUTTONS)
        self.button.currentTextChanged.connect(self._on_change)
        form.addRow("Button", self.button)
        self.count = QComboBox()
        self.count.setEditable(True)
        self.count.addItems(["1", "2", "3", DEPRESS, RELEASE])
        self.count.setToolTip("Number of clicks, or depress / release to hold or let go of the button")
        self.count.currentTextChanged.connect(self._on_change)
        form.addRow("Clicks", self.count)
        self._pages[MouseClick] = page

        page, form = self._page()
        self.dy = self._line(form, "Up", "Lines to scroll up; negative scrolls down")
        self.dx = self._line(form, "Right", "Columns to scroll right; negative scrolls left")
        self._pages[MouseScroll] = page

        page, form = self._page()
        self.command = self._line(form, "Command", "A command line, split like a shell does (no shell runs it)")
        self._pages[Execute] = page

        page, form = self._page()
        self.set_device = self._line(form, "Device", "Empty for the device that sent the event, else a serial or name")
        self.setting = self._line(form, "Setting", "Solaar's setting name, e.g. dpi or smart-shift")
        self.values = self._line(
            form, "Value", "The value; for a setting with keys, the key and the value, e.g. 1, true"
        )
        self._pages[Set] = page

        self.error = QLabel()
        self.error.setStyleSheet("color: palette(link-visited);")
        self.error.setWordWrap(True)

    def _page(self) -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self.addWidget(page)
        return page, form

    def _line(self, form: QFormLayout, label: str, tip: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setToolTip(tip)
        edit.setPlaceholderText(tip)
        edit.textEdited.connect(self._on_change)
        form.addRow(label, edit)
        return edit

    def _combo(self, form: QFormLayout, label: str, items) -> QComboBox:
        combo = QComboBox()
        for value, text in items:
            combo.addItem(text, value)
        combo.currentIndexChanged.connect(self._on_change)
        form.addRow(label, combo)
        return combo

    def _on_change(self, *_args) -> None:
        if not self._loading:
            self.changed.emit()

    def load(self, action: Component | None) -> None:
        self._loading = True
        try:
            self._kind = type(action) if action is not None else None
            if action is None:
                self.setCurrentIndex(0)
                return
            match action:
                case KeyPress():
                    self.keys.setText(" ".join(action.keys))
                    self.key_action.setCurrentIndex(self.key_action.findData(action.action or CLICK))
                case MouseClick():
                    _set_combo_text(self.button, action.button)
                    _set_combo_text(self.count, str(1 if action.count is None else action.count))
                case MouseScroll():
                    self.dx.setText(_show(action.dx))
                    self.dy.setText(_show(action.dy))
                case Execute():
                    self.command.setText(shlex.join(action.args))
                case Set():
                    self.set_device.setText("" if action.device is None else str(action.device))
                    self.setting.setText(action.setting)
                    self.values.setText(", ".join(_show(v) for v in action.values))
            self.setCurrentWidget(self._pages[self._kind])
        finally:
            self._loading = False

    def action(self) -> Component:
        """The action the fields describe, in Solaar's saved shape. Raises Invalid."""
        kind = self._kind
        if kind is KeyPress:
            keys = self.keys.text().split()
            if not keys:
                raise Invalid("Enter at least one key name")
            return KeyPress(keys, self.key_action.currentData())
        if kind is MouseClick:
            button = self.button.currentText().strip()
            if not button:
                raise Invalid("Enter a button name")
            text = self.count.currentText().strip()
            if text in CLICK_ACTIONS:
                return MouseClick(button, text)
            if not text.isdigit():
                raise Invalid("Clicks must be a number, depress or release")
            return MouseClick(button, int(text))
        if kind is MouseScroll:
            return MouseScroll(_number(self.dx.text(), "Right"), _number(self.dy.text(), "Up"))
        if kind is Execute:
            try:
                args = shlex.split(self.command.text())
            except ValueError as e:
                raise Invalid(f"Command: {e}") from e
            if not args:
                raise Invalid("Enter a command")
            return Execute(args)
        if kind is Set:
            device = self.set_device.text().strip() or None
            setting = self.setting.text().strip()
            if not setting:
                raise Invalid("Enter a setting name")
            try:
                values = yaml.safe_load(f"[{self.values.text()}]")
            except yaml.YAMLError as e:
                raise Invalid("Value is not a value or a comma-separated pair") from e
            if not values or not all(v is None or isinstance(v, (str, int, float)) for v in values):
                raise Invalid("Enter a value")
            return Set(device, setting, values)
        raise Invalid("no action selected")


class SimpleEditor(QWidget):
    """Emits edited(SimpleRule, merge_key) on every user change. The rule may be incomplete (no
    actions, an empty name); `problem()` says what is missing. `min_actions` is how many actions
    Remove leaves (1 when editing a rule in place, which must keep one to stay simple)."""

    edited = Signal(object, object)

    def __init__(self, parent=None, min_actions: int = 1):
        super().__init__(parent)
        self.min_actions = min_actions
        self._loading = False
        self._base = SimpleRule(KeyTrigger(""))
        self._actions: list[Component] = []
        self._device_names: dict[Any, str] = {}
        self._devices: list[tuple[str, Any, list[tuple[str, str]]]] = []  # (name, serial, controls)
        self._extra_modifiers: list[str] = []
        self._loaded_fields: tuple[str, ...] = ()

        layout = QVBoxLayout(self)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        font = self.preview.font()
        font.setBold(True)
        self.preview.setFont(font)
        layout.addWidget(self.preview)

        form = QFormLayout()
        self.trigger_kind = QComboBox()
        for value, text in _TRIGGER_KINDS:
            self.trigger_kind.addItem(text, value)
        self.trigger_kind.currentIndexChanged.connect(lambda: self._changed(None))
        form.addRow("When", self.trigger_kind)

        self.key = QComboBox()
        self.key.setEditable(True)
        self.key.setToolTip("The control's name as Solaar knows it. Only diverted controls reach rules.")
        self.key.currentTextChanged.connect(lambda: self._changed("trigger"))
        form.addRow("Button", self.key)

        self.gesture_button = QComboBox()
        self.gesture_button.setEditable(True)
        self.gesture_button.setToolTip("The button held for the gesture; empty for the device's gesture button")
        self.gesture_button.currentTextChanged.connect(lambda: self._changed("trigger"))
        form.addRow("Gesture button", self.gesture_button)
        movements = QWidget()
        row = QHBoxLayout(movements)
        row.setContentsMargins(0, 0, 0, 0)
        self.movements = QLineEdit()
        self.movements.setPlaceholderText("Mouse Up, Mouse Left")
        self.movements.setToolTip("Movements in order, separated by commas. Empty: press and release without moving.")
        self.movements.textEdited.connect(lambda: self._changed("trigger"))
        add_movement = QToolButton()
        add_movement.setText("Add")
        add_movement.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(add_movement)
        for name in _MOVEMENT_NAMES:
            menu.addAction(name, lambda name=name: self._add_movement(name))
        add_movement.setMenu(menu)
        row.addWidget(self.movements, 1)
        row.addWidget(add_movement)
        form.addRow("Movements", movements)
        self._form = form
        self._gesture_rows = (self.gesture_button, movements)

        self.device = QComboBox()
        self.device.setEditable(True)
        self.device.setToolTip("Only for this device: pick one, or type a serial or unit ID")
        self.device.currentTextChanged.connect(self._on_device_text)
        form.addRow("Device", self.device)
        layout.addLayout(form)

        self.modifiers_box = QGroupBox("Only when exactly these modifiers are held")
        self.modifiers_box.setCheckable(True)
        self.modifiers_box.toggled.connect(lambda: self._changed(None))
        mods = QHBoxLayout(self.modifiers_box)
        self.modifier_checks: dict[str, QCheckBox] = {}
        for name, label in MODIFIERS:
            check = QCheckBox(label)
            check.toggled.connect(lambda: self._changed(None))
            self.modifier_checks[name] = check
            mods.addWidget(check)
        self.extra_modifiers = QLabel()
        mods.addWidget(self.extra_modifiers)
        mods.addStretch(1)
        layout.addWidget(self.modifiers_box)

        self.process_box = QGroupBox("Only in a program")
        self.process_box.setCheckable(True)
        self.process_box.toggled.connect(lambda: self._changed(None))
        process_layout = QHBoxLayout(self.process_box)
        self.process = QLineEdit()
        self.process.setPlaceholderText("firefox")
        self.process.setToolTip("Matches a focused window's class or process name that starts with this text")
        self.process.textEdited.connect(lambda: self._changed("process"))
        process_layout.addWidget(self.process)
        layout.addWidget(self.process_box)

        actions_box = QGroupBox("Then")
        actions_layout = QVBoxLayout(actions_box)
        self.action_list = QListWidget()
        self.action_list.setMaximumHeight(120)
        self.action_list.currentRowChanged.connect(self._on_action_selected)
        buttons = QHBoxLayout()
        self.add_action = QToolButton()
        self.add_action.setText("Add action")
        self.add_action.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        add_menu = QMenu(self.add_action)
        for label, factory in NEW_ACTIONS:
            add_menu.addAction(label, lambda factory=factory: self.append_action(factory()))
        self.add_action.setMenu(add_menu)
        self.remove_action = QPushButton("Remove")
        self.remove_action.clicked.connect(self._remove_action)
        self.action_up = QPushButton("Up")
        self.action_up.clicked.connect(lambda: self._move_action(-1))
        self.action_down = QPushButton("Down")
        self.action_down.clicked.connect(lambda: self._move_action(1))
        for b in (self.add_action, self.remove_action, self.action_up, self.action_down):
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.action_editor = ActionEditor()
        self.action_editor.changed.connect(self._on_action_edited)
        actions_layout.addWidget(self.action_list)
        actions_layout.addLayout(buttons)
        actions_layout.addWidget(self.action_editor)
        actions_layout.addWidget(self.action_editor.error)
        layout.addWidget(actions_box)

        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addStretch(1)
        self.set_rule(self._base)

    # Loading

    def set_devices(self, devices: list[tuple[str, Any, list[tuple[str, str]]]], names: Mapping[Any, str]) -> None:
        """Online devices as (name, serial, [(control, mode)]) for the pickers, and names for describe()."""
        self._devices = list(devices)
        self._device_names = dict(names)
        self._loading = True
        try:
            unchanged = self._loaded_fields and self._field_texts() == self._loaded_fields
            self._fill_device_combo(self._device_value())
            self._fill_control_combos()
            if unchanged:
                self._loaded_fields = self._field_texts()
        finally:
            self._loading = False
        self._update_preview()

    def set_rule(self, simple: SimpleRule) -> None:
        """Show `simple` (not emitting edited). Its `written` components are kept for unedited fields."""
        self._loading = True
        try:
            self._base = simple
            self._actions = list(simple.actions)
            trigger = simple.trigger
            if isinstance(trigger, GestureTrigger):
                self.trigger_kind.setCurrentIndex(self.trigger_kind.findData(GESTURE))
                items = list(trigger.movements)
                button = items.pop(0) if items and items[0] not in _MOVEMENT_NAMES else ""
                _set_combo_text(self.gesture_button, button)
                self.movements.setText(", ".join(items))
                self.key.setEditText("")
            else:
                kind = RELEASE_TRIGGER if trigger.action == RELEASED else PRESS
                self.trigger_kind.setCurrentIndex(self.trigger_kind.findData(kind))
                _set_combo_text(self.key, trigger.key)
                self.gesture_button.setEditText("")
                self.movements.clear()
            self._fill_device_combo(simple.device)
            self._fill_control_combos()
            self.modifiers_box.setChecked(simple.modifiers is not None)
            mods = simple.modifiers or []
            for name, check in self.modifier_checks.items():
                check.setChecked(name in mods)
            known = {name for name, _ in MODIFIERS}
            self._extra_modifiers = [m for m in mods if m not in known]
            self.extra_modifiers.setText(f"also: {', '.join(self._extra_modifiers)}" if self._extra_modifiers else "")
            self.process_box.setChecked(simple.process is not None)
            self.process.setText(simple.process or "")
            self._loaded_fields = self._field_texts()
            self._fill_action_list()
            self.action_list.setCurrentRow(0 if self._actions else -1)
            self.action_editor.load(self._actions[0] if self._actions else None)
            self.action_editor.error.clear()
        finally:
            self._loading = False
        self._show_trigger_rows()
        self._update_buttons()
        self._update_preview()

    def _fill_device_combo(self, value: Any) -> None:
        self.device.clear()
        self.device.addItem("Any device", None)
        for name, serial, _controls in self._devices:
            self.device.addItem(name, serial)
            self.device.setItemData(self.device.count() - 1, f"Serial {serial}", Qt.ItemDataRole.ToolTipRole)
        if value is None:
            self.device.setCurrentIndex(0)
            return
        for i in range(1, self.device.count()):
            data = self.device.itemData(i)
            if type(data) is type(value) and data == value:
                self.device.setCurrentIndex(i)
                return
        self.device.addItem(_show(value) if not isinstance(value, str) else value, value)
        self.device.setCurrentIndex(self.device.count() - 1)

    def _fill_control_combos(self) -> None:
        device = self._device_value()
        chosen = [d for d in self._devices if device is not None and device in (d[0], d[1])]
        controls: dict[str, str] = {}
        for _name, _serial, device_controls in chosen or self._devices:  # any device: every device's controls
            for control, mode in device_controls:
                controls.setdefault(control, mode)
        for combo, blank in ((self.key, False), (self.gesture_button, True)):
            text = combo.currentText()
            combo.clear()
            if blank:
                combo.addItem("")
            for control, mode in controls.items():
                combo.addItem(control)
                combo.setItemData(combo.count() - 1, mode, Qt.ItemDataRole.ToolTipRole)
            _set_combo_text(combo, text)

    def _fill_action_list(self) -> None:
        self.action_list.clear()
        for action in self._actions:
            self.action_list.addItem(QListWidgetItem(describe_action(action, self._device_names)))

    # Reading the form

    def _field_texts(self) -> tuple[str, ...]:
        """What the trigger and device fields show, to tell whether the user changed them."""
        return (
            self.trigger_kind.currentData(),
            self.key.currentText(),
            self.gesture_button.currentText(),
            self.movements.text(),
            self.device.currentText(),
        )

    def _device_value(self) -> Any:
        if self._loaded_fields and self.device.currentText() == self._loaded_fields[4]:
            return self._base.device  # unchanged: exactly as loaded, whatever its type
        text = self.device.currentText()
        index = self.device.currentIndex()
        if index < 0 or self.device.itemText(index) != text:
            index = self.device.findText(text, Qt.MatchFlag.MatchExactly)
        if index >= 0:
            return self.device.itemData(index)
        return text.strip() or None

    def _trigger(self):
        if self._loaded_fields and self._field_texts()[:4] == self._loaded_fields[:4]:
            return self._base.trigger  # unchanged: exactly as loaded
        kind = self.trigger_kind.currentData()
        if kind == GESTURE:
            button = self.gesture_button.currentText().strip()
            items = [m.strip() for m in self.movements.text().split(",") if m.strip()]
            return GestureTrigger(([button] if button else []) + items)
        return KeyTrigger(self.key.currentText().strip(), RELEASED if kind == RELEASE_TRIGGER else PRESSED)

    def _modifiers(self) -> list[str] | None:
        if not self.modifiers_box.isChecked():
            return None
        checked = {name for name, check in self.modifier_checks.items() if check.isChecked()}
        known = {name for name, _ in MODIFIERS}
        before = self._base.modifiers or []
        kept = [m for m in before if m in checked or m not in known]  # keep their order, and unknown names
        return kept + [name for name, _ in MODIFIERS if name in checked and name not in kept]

    def current(self) -> SimpleRule:
        """The rule as the form shows it (possibly incomplete; see problem())."""
        return replace(
            self._base,
            trigger=self._trigger(),
            actions=list(self._actions),
            device=self._device_value(),
            modifiers=self._modifiers(),
            process=self.process.text() if self.process_box.isChecked() else None,
        )

    def problem(self) -> str | None:
        """Why the form's rule cannot be written yet, or None."""
        simple = self.current()
        trigger = simple.trigger
        if isinstance(trigger, KeyTrigger) and not trigger.key:
            return "Choose the button that triggers the rule."
        if isinstance(trigger, GestureTrigger) and not trigger.movements:
            return "Enter the gesture's button or movements."
        if not simple.actions:
            return "Add an action."
        try:
            generate(simple)
        except NotSimple as e:
            return str(e)
        return None

    # Changes

    def _changed(self, merge_key: str | None) -> None:
        if self._loading:
            return
        self._show_trigger_rows()
        self._update_preview()
        self.edited.emit(self.current(), merge_key)

    def _on_device_text(self) -> None:
        if self._loading:
            return
        self._loading = True
        try:
            self._fill_control_combos()
        finally:
            self._loading = False
        self._changed("device")

    def _add_movement(self, name: str) -> None:
        text = self.movements.text().strip()
        self.movements.setText(f"{text}, {name}" if text else name)
        self._changed(None)

    def _show_trigger_rows(self) -> None:
        gesture = self.trigger_kind.currentData() == GESTURE
        self._form.setRowVisible(self.key, not gesture)
        for widget in self._gesture_rows:
            self._form.setRowVisible(widget, gesture)

    def _update_preview(self) -> None:
        problem = self.problem()
        try:
            text = describe(self.current(), self._device_names)
        except Exception:  # an incomplete rule may not describe
            text = ""
        self.preview.setText(text)
        self.message.setText(problem or "")

    def _update_buttons(self) -> None:
        row = self.action_list.currentRow()
        self.remove_action.setEnabled(row >= 0 and len(self._actions) > self.min_actions)
        self.action_up.setEnabled(row > 0)
        self.action_down.setEnabled(0 <= row < len(self._actions) - 1)

    def _on_action_selected(self, row: int) -> None:
        if not self._loading:
            self.action_editor.load(self._actions[row] if 0 <= row < len(self._actions) else None)
            self.action_editor.error.clear()
        self._update_buttons()

    def _on_action_edited(self) -> None:
        row = self.action_list.currentRow()
        if not 0 <= row < len(self._actions):
            return
        try:
            action = self.action_editor.action()
        except Invalid as e:
            self.action_editor.error.setText(str(e))
            return
        self.action_editor.error.clear()
        self._actions[row] = action
        self.action_list.item(row).setText(describe_action(action, self._device_names))
        self._changed(f"action {row}")

    def append_action(self, action: Component) -> None:
        self._actions.append(action)
        self._fill_action_list()
        self.action_list.setCurrentRow(len(self._actions) - 1)
        self._changed(None)

    def _remove_action(self) -> None:
        row = self.action_list.currentRow()
        if not 0 <= row < len(self._actions) or len(self._actions) <= self.min_actions:
            return
        del self._actions[row]
        self._fill_action_list()
        self.action_list.setCurrentRow(min(row, len(self._actions) - 1))
        self._changed(None)

    def _move_action(self, delta: int) -> None:
        row = self.action_list.currentRow()
        new = row + delta
        if not (0 <= row < len(self._actions) and 0 <= new < len(self._actions)):
            return
        self._actions.insert(new, self._actions.pop(row))
        self._fill_action_list()
        self.action_list.setCurrentRow(new)
        self._changed(None)
