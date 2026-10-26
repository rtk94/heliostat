# SPDX-License-Identifier: GPL-2.0-or-later
"""One-line English summaries of simple rules.

Names Solaar uses are shown as written, except modifier and key names, which get the labels printed
on keys (Control_L is Ctrl, XF86_AudioMute is Mute). Phrasing follows what Solaar does, checked
against .solaar/1.1.14 and .solaar/1.1.20 `lib/logitech_receiver/diversion.py`: KeyPress presses its
keys in order and releases them in reverse (a chord), MouseScroll's positive dy scrolls up and positive
dx right, and a MouseGesture item that is not a movement name is the initiating control when first,
otherwise a control pressed during the gesture.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from typing import Any

from heliostat.model import (
    CLICK,
    DEPRESS,
    RELEASE,
    RELEASED,
    Component,
    Execute,
    KeyPress,
    MouseClick,
    MouseScroll,
    Set,
)
from heliostat.simple.rule import GestureTrigger, KeyTrigger, SimpleRule
from heliostat.solaar.names import MOVEMENTS

# The movement names are the same in every pinned version.
_MOVEMENTS = frozenset(name for names in MOVEMENTS.values() for name in names)

_MODIFIER_LABELS = {"Control": "Ctrl"}

_KEY_LABELS = {
    "Control_L": "Ctrl",
    "Control_R": "Right Ctrl",
    "Shift_L": "Shift",
    "Shift_R": "Right Shift",
    "Alt_L": "Alt",
    "Alt_R": "Right Alt",
    "Super_L": "Super",
    "Super_R": "Right Super",
    "Meta_L": "Meta",
    "Meta_R": "Right Meta",
    "ISO_Level3_Shift": "AltGr",
    "Return": "Enter",
    "KP_Enter": "Keypad Enter",
    "Escape": "Esc",
    "BackSpace": "Backspace",
    "Prior": "Page Up",
    "Next": "Page Down",
    "space": "Space",
    "Print": "Print Screen",
    "XF86_AudioMute": "Mute",
    "XF86_AudioMicMute": "Mic Mute",
    "XF86_AudioRaiseVolume": "Volume Up",
    "XF86_AudioLowerVolume": "Volume Down",
    "XF86_AudioPlay": "Play",
    "XF86_AudioPause": "Pause",
    "XF86_AudioStop": "Stop",
    "XF86_AudioNext": "Next Track",
    "XF86_AudioPrev": "Previous Track",
    "XF86_MonBrightnessUp": "Brightness Up",
    "XF86_MonBrightnessDown": "Brightness Down",
}

_BUTTON_LABELS = {
    "left": "left button",
    "middle": "middle button",
    "right": "right button",
    "scroll_up": "scroll-up button",
    "scroll_down": "scroll-down button",
    "scroll_left": "scroll-left button",
    "scroll_right": "scroll-right button",
}


def describe(rule: SimpleRule, device_names: Mapping[Any, str] | None = None) -> str:
    """E.g. "When Back Button on MX Master 3 is pressed: press Ctrl+Tab".

    `device_names` maps Device condition and Set action ids (serials) to names to show instead.
    """
    on = f" on {_device(rule.device, device_names)}" if rule.device is not None else ""
    when = [_trigger(rule.trigger, on)]
    if rule.modifiers is not None:
        held = "+".join(_MODIFIER_LABELS.get(m, m) for m in rule.modifiers)
        when.append(f"with {held} held" if held else "with no modifier held")
    if rule.process is not None:
        when.append(f"in {rule.process}")
    actions = ", then ".join(_action(a, device_names) for a in rule.actions)
    return f"When {' '.join(when)}: {actions}"


def describe_action(action: Component, device_names: Mapping[Any, str] | None = None) -> str:
    """One simple action in words, e.g. "press Ctrl+Tab"."""
    return _action(action, device_names)


def _device(device: Any, device_names: Mapping[Any, str] | None) -> str:
    if device_names is not None:
        name = device_names.get(device)
        if name is not None:
            return name
    return _show(device)


def _trigger(trigger: KeyTrigger | GestureTrigger, on: str) -> str:
    if isinstance(trigger, KeyTrigger):
        return f"{trigger.key}{on} is {RELEASED if trigger.action == RELEASED else 'pressed'}"
    movements = list(trigger.movements)
    button = "a gesture button"
    if movements and movements[0] not in _MOVEMENTS:
        button = movements.pop(0)
    if not movements:
        return f"{button}{on} is pressed and released without moving the mouse"
    steps = ", then ".join(_gesture_step(m) for m in movements)
    return f"{button}{on} is held and you {steps}"


def _gesture_step(item: str) -> str:
    if item in _MOVEMENTS:
        return "move " + item.removeprefix("Mouse ").lower()
    return f"press {item}"


def _action(action: Component, device_names: Mapping[Any, str] | None) -> str:
    match action:
        case KeyPress():
            keys = "+".join(_key(k) for k in action.keys)
            verb = {DEPRESS: "hold down", RELEASE: "release"}.get(action.action or CLICK, "press")
            return f"{verb} {keys}"
        case MouseClick():
            return _mouse_click(action)
        case MouseScroll():
            return _mouse_scroll(action.dx, action.dy)
        case Execute():
            return f"run {shlex.join(action.args)}" if action.args else "run nothing"
        case Set():
            on = f" on {_device(action.device, device_names)}" if action.device is not None else ""
            values = [_show(v) for v in action.values]
            if len(values) == 2:
                return f"set {action.setting} for {values[0]} to {values[1]}{on}"
            return f"set {action.setting} to {', '.join(values)}{on}"
    raise AssertionError(f"not a simple action: {action!r}")


def _key(name: str) -> str:
    if name in _KEY_LABELS:
        return _KEY_LABELS[name]
    if len(name) == 1 and name.isalpha():
        return name.upper()
    return name


def _mouse_click(action: MouseClick) -> str:
    button = _BUTTON_LABELS.get(action.button)
    if button is None:
        number = action.button.removeprefix("button")
        button = f"button {number}" if number.isdigit() else action.button
    count = 1 if action.count is None else action.count
    if count == DEPRESS:
        return f"hold down the {button}"
    if count == RELEASE:
        return f"release the {button}"
    if count in (1, CLICK):
        return f"click the {button}"
    if count == 2:
        return f"double-click the {button}"
    return f"click the {button} {count} times"


def _mouse_scroll(dx: int | float, dy: int | float) -> str:
    parts = []
    if dy:
        parts.append(f"{'up' if dy > 0 else 'down'} {_show(abs(dy))}")
    if dx:
        parts.append(f"{'right' if dx > 0 else 'left'} {_show(abs(dx))}")
    return "scroll " + " and ".join(parts) if parts else "scroll by 0"


def _show(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
