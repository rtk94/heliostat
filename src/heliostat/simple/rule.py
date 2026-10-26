# SPDX-License-Identifier: GPL-2.0-or-later
"""Simple rules: the common shape the plain-language editor handles.

A simple rule is a trigger, at most one each of Device, Modifiers and Process, then one or more
actions (KeyPress, MouseClick, MouseScroll, Execute, Set). The trigger is a Key condition (pressed or
released) or a MouseGesture condition. Conditions may come in any order, but all of them come before
the actions. There is no "any" trigger: Solaar has none, and an Or of pressed and released fires the
actions twice per click, so such a rule stays in the advanced editor.

`recognize(rule)` returns a SimpleRule or None; `generate(simple)` gives the Rule back. A recognized
rule regenerates exactly as it was written: each condition component remembers how it was loaded
(`SimpleRule.written`), and is written back unchanged unless its value was edited. Actions are the
model's own components, which keep their argument shapes (deviation D2). Condition order is kept too;
it is not only formatting: Solaar stops evaluating a rule at its first false condition, so a Process
condition before the trigger runs on every notification, and on Wayland outside GNOME its None result
stops all later rules (lint HL006). New conditions go after the existing ones, in the order trigger,
Device, Modifiers, Process.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from heliostat.model import (
    PRESSED,
    RELEASED,
    Component,
    Device,
    Execute,
    Key,
    KeyPress,
    Later,
    Modifiers,
    MouseClick,
    MouseGesture,
    MouseScroll,
    Process,
    Raw,
    Rule,
    Set,
)

TRIGGER_KEY_ACTIONS = (PRESSED, RELEASED)

ACTION_TYPES: tuple[type[Component], ...] = (KeyPress, MouseClick, MouseScroll, Execute, Set)
SimpleAction = KeyPress | MouseClick | MouseScroll | Execute | Set
DeviceId = str | int | float | bool

# Condition slots, in the order new rules write them.
TRIGGER, DEVICE, MODIFIERS, PROCESS = "trigger", "device", "modifiers", "process"
SLOTS = (TRIGGER, DEVICE, MODIFIERS, PROCESS)


@dataclass
class KeyTrigger:
    """A Key condition: `action` is pressed or released."""

    key: str
    action: str = PRESSED


@dataclass
class GestureTrigger:
    """A MouseGesture condition: an optional initiating control, then movements or controls."""

    movements: list[str] = field(default_factory=list)


Trigger = KeyTrigger | GestureTrigger


@dataclass
class SimpleRule:
    """A rule in the simple shape. `modifiers` [] means no modifier held; None means no condition.

    `written` maps each condition slot of a recognized rule to its component as loaded, in rule order.
    It is not part of equality: two SimpleRules that mean the same rule compare equal.
    """

    trigger: Trigger
    actions: list[SimpleAction] = field(default_factory=list)
    device: DeviceId | None = None
    modifiers: list[str] | None = None
    process: str | None = None
    written: dict[str, Component] = field(default_factory=dict, compare=False, repr=False)


class NotSimple(ValueError):
    """A SimpleRule that generate() cannot write, or a rule recognize() does not accept."""


def recognize(component: Component) -> SimpleRule | None:
    """The SimpleRule for a rule in the simple shape; None sends it to the advanced editor."""
    try:
        return _recognize(component)
    except NotSimple:
        return None


def not_simple_reason(component: Component) -> str | None:
    """Why a rule is not simple, or None if it is."""
    try:
        _recognize(component)
    except NotSimple as e:
        return str(e)
    return None


def generate(simple: SimpleRule) -> Rule:
    """The Rule for a SimpleRule. Unedited conditions are written as loaded; new ones in Solaar's shape."""
    _check(simple)
    values = _values(simple)
    order = [s for s in simple.written if s in values] + [s for s in SLOTS if s in values and s not in simple.written]
    components = []
    for slot in order:
        written = simple.written.get(slot)
        if written is not None and _same(_slot_value(slot, written), values[slot]):
            components.append(copy.deepcopy(written))
        else:
            components.append(_build(slot, values[slot]))
    components.extend(copy.deepcopy(a) for a in simple.actions)
    return Rule(components)


def _recognize(component: Component) -> SimpleRule:
    if not isinstance(component, Rule):
        raise NotSimple("not a rule" if isinstance(component, Raw) else f"a {component.TYPE} component, not a rule")
    components = component.components
    split = next((i for i, c in enumerate(components) if isinstance(c, ACTION_TYPES)), len(components))
    conditions, actions = components[:split], components[split:]
    written: dict[str, Component] = {}
    for c in conditions:
        slot = _slot_of(c)
        if slot is None:
            raise NotSimple(_kind(c))
        if isinstance(c, MouseGesture) and not c.movements:
            raise NotSimple("MouseGesture with no movements")
        if slot in written:
            raise NotSimple(f"more than one {'Key or MouseGesture trigger' if slot == TRIGGER else c.TYPE} condition")
        written[slot] = c
    if TRIGGER not in written:
        raise NotSimple("no Key or MouseGesture trigger")
    if not actions:
        raise NotSimple("no action")
    for c in actions:
        if not isinstance(c, ACTION_TYPES):
            raise NotSimple(f"{_kind(c)} after an action")
    written = copy.deepcopy(written)
    return SimpleRule(
        trigger=_slot_value(TRIGGER, written[TRIGGER]),
        actions=copy.deepcopy(actions),
        device=_slot_value(DEVICE, written[DEVICE]) if DEVICE in written else None,
        modifiers=_slot_value(MODIFIERS, written[MODIFIERS]) if MODIFIERS in written else None,
        process=_slot_value(PROCESS, written[PROCESS]) if PROCESS in written else None,
        written=written,
    )


def _kind(component: Component) -> str:
    if isinstance(component, Raw):
        name = component.type_name
        return f"unrecognized {name} component" if name else "unrecognized component"
    if isinstance(component, Rule):
        return "nested rule"
    if isinstance(component, Later):
        return "Later action"
    if isinstance(component, ACTION_TYPES):
        return f"{component.TYPE} action"
    return f"{component.TYPE} condition"


def _slot_of(component: Component) -> str | None:
    if isinstance(component, (Key, MouseGesture)):
        return TRIGGER
    if isinstance(component, Device):
        return DEVICE
    if isinstance(component, Modifiers):
        return MODIFIERS
    if isinstance(component, Process):
        return PROCESS
    return None


def _slot_value(slot: str, component: Component) -> Any:
    match slot, component:
        case "trigger", Key():
            return KeyTrigger(component.key, component.action or PRESSED)
        case "trigger", MouseGesture():
            return GestureTrigger(list(component.movements))
        case "device", Device():
            return component.device
        case "modifiers", Modifiers():
            return list(component.modifiers)
        case "process", Process():
            return component.process
    raise AssertionError(f"no {slot} value in {component!r}")


def _values(simple: SimpleRule) -> dict[str, Any]:
    values: dict[str, Any] = {TRIGGER: simple.trigger}
    if simple.device is not None:
        values[DEVICE] = simple.device
    if simple.modifiers is not None:
        values[MODIFIERS] = simple.modifiers
    if simple.process is not None:
        values[PROCESS] = simple.process
    return values


def _build(slot: str, value: Any) -> Component:
    """A new condition in the shape Solaar's save writes."""
    if isinstance(value, KeyTrigger):
        return Key(value.key, value.action)
    if isinstance(value, GestureTrigger):
        return MouseGesture(list(value.movements))
    if slot == DEVICE:
        return Device(value)
    if slot == MODIFIERS:
        return Modifiers(list(value))
    return Process(value)


def _same(a: Any, b: Any) -> bool:
    """Equal and of the same types, so a loaded `Device: 1` is not mistaken for `Device: true`."""
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and a == b


def _check(simple: SimpleRule) -> None:
    trigger = simple.trigger
    if isinstance(trigger, KeyTrigger):
        if not isinstance(trigger.key, str):
            raise NotSimple("Key trigger name is not a string")
        if trigger.action not in TRIGGER_KEY_ACTIONS:
            raise NotSimple(f"Key trigger action is not one of {', '.join(TRIGGER_KEY_ACTIONS)}")
    elif isinstance(trigger, GestureTrigger):
        if not trigger.movements or not all(isinstance(m, str) for m in trigger.movements):
            raise NotSimple("MouseGesture trigger has no movements")
    else:
        raise NotSimple("no Key or MouseGesture trigger")
    if not simple.actions:
        raise NotSimple("no action")
    for a in simple.actions:
        if not isinstance(a, ACTION_TYPES):
            raise NotSimple(f"{_kind(a)}: not a simple action")
    if simple.device is not None and not isinstance(simple.device, (str, int, float)):
        raise NotSimple("Device is not a scalar")
    if simple.modifiers is not None and not all(isinstance(m, str) for m in simple.modifiers):
        raise NotSimple("Modifiers are not strings")
    if simple.process is not None and not isinstance(simple.process, str):
        raise NotSimple("Process is not a string")
