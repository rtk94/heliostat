# SPDX-License-Identifier: GPL-2.0-or-later
"""Typed rule components, parsed from and serialized back to PyYAML structures.

Each component mirrors one entry of Solaar's `diversion.COMPONENTS` (checked against
.solaar/1.1.14 and .solaar/1.1.20 `lib/logitech_receiver/diversion.py`, whose component code is the
same apart from the Feature name lookup).

`from_yaml(obj)` takes the one-key mapping as loaded (`{"Key": "Back Button"}`); `to_yaml()` returns
it again in the same shape (deviation D2 in docs/decisions.md). Argument values keep their loaded
scalar types, and a component remembers which of the argument shapes Solaar accepts it was written in
(`Key: Back Button` vs `Key: [Back Button]` vs `Key: [Back Button, pressed]`, a scalar vs a one-item
list), so output matches input.

A component built in code leaves its form fields at their defaults and is written in the shape
Solaar's own save writes: the shape its `data()` returns, with one-item scalar lists collapsed to the
scalar (`Modifiers: Shift`, `Test: crown_tap`, `KeyPress: [key, click]`). That is the only place
Heliostat collapses a list; a loaded one-item list is never collapsed, and `rulesfile.dumps` never
collapses anything.

A typed class only accepts argument shapes Solaar reads as that component's arguments. Anything else
(an unknown type, a wrong argument type or shape) becomes `Raw` and is kept verbatim.
"""

from __future__ import annotations

import copy
import enum
from dataclasses import dataclass, field
from typing import Any, ClassVar

# Key actions (diversion.Key.DOWN / UP).
PRESSED, RELEASED = "pressed", "released"
KEY_ACTIONS = (PRESSED, RELEASED)
# KeyPress and MouseClick actions (diversion.CLICK, DEPRESS, RELEASE).
CLICK, DEPRESS, RELEASE = "click", "depress", "release"
CLICK_ACTIONS = (CLICK, DEPRESS, RELEASE)


class _NoParameter(enum.Enum):
    NO_PARAMETER = "no parameter"


# Test.parameter when the test has none. An enum member, so it survives copy.deepcopy.
NO_PARAMETER = _NoParameter.NO_PARAMETER


class MalformedComponent(ValueError):
    """A known component type whose argument has a shape the typed class does not accept."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float))


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _scalar_or_list(items: list[Any], listed: bool | None) -> Any:
    """A list argument in its form: listed True (loaded as a list) keeps a one-item list, False
    (loaded as a bare scalar) or None (built in code, Solaar's saved shape) writes one item bare."""
    if listed is not True and len(items) == 1:
        return items[0]
    return list(items)


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise MalformedComponent(message)


class Component:
    """Base class of every rule component."""

    TYPE: ClassVar[str]

    @classmethod
    def from_yaml(cls, obj: Any) -> Component:
        _require(isinstance(obj, dict) and len(obj) == 1 and cls.TYPE in obj, f"not a {cls.TYPE} component")
        return cls._from_arg(obj[cls.TYPE])

    @classmethod
    def _from_arg(cls, arg: Any) -> Component:
        raise NotImplementedError

    def to_yaml(self) -> Any:
        return {self.TYPE: self._arg()}

    def _arg(self) -> Any:
        raise NotImplementedError


def component_from_yaml(obj: Any) -> Component:
    """Parse one rule component, falling back to `Raw` for anything unknown or malformed."""
    if not (isinstance(obj, dict) and len(obj) == 1):
        return Raw(copy.deepcopy(obj), reason="not a one-key mapping")
    ((name, _),) = obj.items()
    cls = COMPONENT_TYPES.get(name) if isinstance(name, str) else None
    if cls is None:
        return Raw(copy.deepcopy(obj), reason=f"unknown component type {name!r}")
    try:
        return cls.from_yaml(obj)
    except MalformedComponent as e:
        return Raw(copy.deepcopy(obj), reason=str(e))


def _components_from_list(arg: Any, name: str) -> list[Component]:
    _require(isinstance(arg, list), f"{name} argument is not a list")
    return [component_from_yaml(c) for c in arg]


@dataclass
class Raw(Component):
    """An unknown or malformed component, kept exactly as loaded.

    `data` is the whole loaded item (normally a one-key mapping). `reason` says why it is not typed.
    """

    TYPE: ClassVar[str] = "<raw>"

    data: Any
    reason: str = field(default="", compare=False)

    @classmethod
    def from_yaml(cls, obj: Any) -> Raw:
        return cls(copy.deepcopy(obj))

    def to_yaml(self) -> Any:
        return copy.deepcopy(self.data)

    @property
    def type_name(self) -> str | None:
        """The component type key, if `data` is a one-key mapping with a string key."""
        if isinstance(self.data, dict) and len(self.data) == 1:
            (name,) = self.data
            if isinstance(name, str):
                return name
        return None


# Sub-rules and logical conditions


@dataclass
class Rule(Component):
    TYPE: ClassVar[str] = "Rule"

    components: list[Component] = field(default_factory=list)

    @classmethod
    def _from_arg(cls, arg: Any) -> Rule:
        return cls(_components_from_list(arg, cls.TYPE))

    def _arg(self) -> Any:
        return [c.to_yaml() for c in self.components]


@dataclass
class Not(Component):
    TYPE: ClassVar[str] = "Not"

    component: Component
    # Loaded as a one-item list (`Not: [Process: kwin]`). Solaar's data() writes the bare mapping.
    listed: bool = False

    @classmethod
    def _from_arg(cls, arg: Any) -> Not:
        listed = isinstance(arg, list)
        if listed:
            _require(len(arg) == 1, "Not list argument does not have exactly one item")
            arg = arg[0]
        _require(isinstance(arg, dict), "Not argument is not a component")
        return cls(component_from_yaml(arg), listed)

    def _arg(self) -> Any:
        inner = self.component.to_yaml()
        return [inner] if self.listed else inner


@dataclass
class Or(Component):
    TYPE: ClassVar[str] = "Or"

    components: list[Component] = field(default_factory=list)

    @classmethod
    def _from_arg(cls, arg: Any) -> Or:
        return cls(_components_from_list(arg, cls.TYPE))

    def _arg(self) -> Any:
        return [c.to_yaml() for c in self.components]


@dataclass
class And(Component):
    TYPE: ClassVar[str] = "And"

    components: list[Component] = field(default_factory=list)

    @classmethod
    def _from_arg(cls, arg: Any) -> And:
        return cls(_components_from_list(arg, cls.TYPE))

    def _arg(self) -> Any:
        return [c.to_yaml() for c in self.components]


# Conditions with a single string or scalar argument


@dataclass
class Process(Component):
    TYPE: ClassVar[str] = "Process"

    process: str

    @classmethod
    def _from_arg(cls, arg: Any) -> Process:
        _require(isinstance(arg, str), f"{cls.TYPE} argument is not a string")
        return cls(arg)

    def _arg(self) -> Any:
        return self.process


@dataclass
class MouseProcess(Component):
    TYPE: ClassVar[str] = "MouseProcess"

    process: str

    @classmethod
    def _from_arg(cls, arg: Any) -> MouseProcess:
        _require(isinstance(arg, str), f"{cls.TYPE} argument is not a string")
        return cls(arg)

    def _arg(self) -> Any:
        return self.process


class FeatureArgForm(enum.Enum):
    """How a Feature argument is spelled, for lint (see deviation D1 in docs/decisions.md)."""

    NAME = "name"  # underscore spelling (THUMB_WHEEL) or a one-word name (CROWN); every version loads it
    SPACED = "spaced"  # THUMB WHEEL: Solaar 1.1.14 loads it as None, 1.1.15+ accept it
    NONE = "none"  # the literal None that Solaar writes after it lost the feature


def feature_argument_form(argument: str) -> FeatureArgForm:
    if argument == "None":
        return FeatureArgForm.NONE
    if " " in argument:
        return FeatureArgForm.SPACED
    return FeatureArgForm.NAME


@dataclass
class Feature(Component):
    """Feature condition. The argument is kept exactly as loaded (deviation D1)."""

    TYPE: ClassVar[str] = "Feature"

    feature: str

    @classmethod
    def new(cls, name: str) -> Feature:
        """A new Feature condition, written in the underscore spelling every Solaar version loads."""
        return cls(name.replace(" ", "_"))

    @property
    def argument_form(self) -> FeatureArgForm:
        return feature_argument_form(self.feature)

    @classmethod
    def _from_arg(cls, arg: Any) -> Feature:
        _require(isinstance(arg, str), "Feature argument is not a string")
        return cls(arg)

    def _arg(self) -> Any:
        return self.feature


@dataclass
class Report(Component):
    TYPE: ClassVar[str] = "Report"

    report: int

    @classmethod
    def _from_arg(cls, arg: Any) -> Report:
        _require(_is_int(arg), "Report argument is not an integer")
        return cls(arg)

    def _arg(self) -> Any:
        return self.report


@dataclass
class KeyIsDown(Component):
    TYPE: ClassVar[str] = "KeyIsDown"

    key: str

    @classmethod
    def _from_arg(cls, arg: Any) -> KeyIsDown:
        _require(isinstance(arg, str), "KeyIsDown argument is not a string")
        return cls(arg)

    def _arg(self) -> Any:
        return self.key


@dataclass
class Active(Component):
    TYPE: ClassVar[str] = "Active"

    device: str | int | float | bool

    @classmethod
    def _from_arg(cls, arg: Any) -> Active:
        _require(_is_scalar(arg), f"{cls.TYPE} argument is not a scalar")
        return cls(arg)

    def _arg(self) -> Any:
        return self.device


@dataclass
class Device(Component):
    """Device condition. An all-digit serial loads as an int and stays one."""

    TYPE: ClassVar[str] = "Device"

    device: str | int | float | bool

    @classmethod
    def _from_arg(cls, arg: Any) -> Device:
        _require(_is_scalar(arg), f"{cls.TYPE} argument is not a scalar")
        return cls(arg)

    def _arg(self) -> Any:
        return self.device


@dataclass
class Host(Component):
    TYPE: ClassVar[str] = "Host"

    host: str | int | float | bool

    @classmethod
    def _from_arg(cls, arg: Any) -> Host:
        _require(_is_scalar(arg), f"{cls.TYPE} argument is not a scalar")
        return cls(arg)

    def _arg(self) -> Any:
        return self.host


# Conditions with list arguments


def _setting_args(arg: Any, name: str) -> tuple[Any, str, list[Any]]:
    _require(isinstance(arg, list) and len(arg) >= 3, f"{name} argument is not a list of at least 3 items")
    _require(all(a is None or _is_scalar(a) for a in arg), f"{name} argument has a non-scalar item")
    _require(isinstance(arg[1], str), f"{name} setting name is not a string")
    return arg[0], arg[1], list(arg[2:])


@dataclass
class Setting(Component):
    """Setting condition: `[device, setting, value...]` or `[device, setting, key, value]`.

    `device` is None for the device that sent the notification.
    """

    TYPE: ClassVar[str] = "Setting"

    device: str | int | float | bool | None
    setting: str
    values: list[Any] = field(default_factory=list)

    @classmethod
    def _from_arg(cls, arg: Any) -> Setting:
        return cls(*_setting_args(arg, cls.TYPE))

    def _arg(self) -> Any:
        return [self.device, self.setting, *self.values]


@dataclass
class Modifiers(Component):
    TYPE: ClassVar[str] = "Modifiers"

    modifiers: list[str] = field(default_factory=list)
    listed: bool | None = None  # True loaded as a list, False as a bare string, None built in code

    @classmethod
    def _from_arg(cls, arg: Any) -> Modifiers:
        if isinstance(arg, str):
            return cls([arg], listed=False)
        _require(_is_str_list(arg), "Modifiers argument is not a string or list of strings")
        return cls(list(arg), listed=True)

    def _arg(self) -> Any:
        return _scalar_or_list(self.modifiers, self.listed)


@dataclass
class Key(Component):
    """Key condition. `action` None means it was not written (Solaar assumes pressed)."""

    TYPE: ClassVar[str] = "Key"

    key: str
    action: str | None = PRESSED
    listed: bool = True

    @classmethod
    def _from_arg(cls, arg: Any) -> Key:
        if isinstance(arg, str):
            return cls(arg, None, listed=False)
        _require(isinstance(arg, list) and len(arg) in (1, 2), "Key argument is not a name or [name, action]")
        _require(isinstance(arg[0], str), "Key name is not a string")
        if len(arg) == 1:
            return cls(arg[0], None, listed=True)
        _require(arg[1] in KEY_ACTIONS, f"Key action is not one of {', '.join(KEY_ACTIONS)}")
        return cls(arg[0], arg[1], listed=True)

    def _arg(self) -> Any:
        if self.action is None:
            return [self.key] if self.listed else self.key
        return [self.key, self.action]


@dataclass
class Test(Component):
    """Test condition: a test name, optionally with a parameter."""

    TYPE: ClassVar[str] = "Test"
    __test__ = False  # not a pytest test class

    test: str
    parameter: Any = NO_PARAMETER
    listed: bool | None = None  # True loaded as a list, False as a bare name, None built in code

    @property
    def has_parameter(self) -> bool:
        return self.parameter is not NO_PARAMETER

    @classmethod
    def _from_arg(cls, arg: Any) -> Test:
        if isinstance(arg, str):
            return cls(arg, listed=False)
        # Solaar turns an all-integer Test into TestBytes; keep those (and anything else) verbatim.
        _require(isinstance(arg, list) and len(arg) in (1, 2), "Test argument is not a name or [name, parameter]")
        _require(isinstance(arg[0], str), "Test name is not a string")
        if len(arg) == 1:
            return cls(arg[0], listed=True)
        _require(arg[1] is None or _is_scalar(arg[1]), "Test parameter is not a scalar")
        return cls(arg[0], arg[1], listed=True)

    def _arg(self) -> Any:
        if self.has_parameter:
            return [self.test, self.parameter]
        return _scalar_or_list([self.test], self.listed)


@dataclass
class TestBytes(Component):
    """TestBytes condition: `[start, end, mask]` or `[start, end, min, max]`."""

    TYPE: ClassVar[str] = "TestBytes"
    __test__ = False  # not a pytest test class

    values: list[int]

    @classmethod
    def _from_arg(cls, arg: Any) -> TestBytes:
        _require(
            isinstance(arg, list) and len(arg) in (3, 4) and all(_is_int(a) for a in arg),
            "TestBytes argument is not a list of 3 or 4 integers",
        )
        return cls(list(arg))

    def _arg(self) -> Any:
        return list(self.values)


@dataclass
class MouseGesture(Component):
    """MouseGesture condition: an optional initiating key name, then movement names."""

    TYPE: ClassVar[str] = "MouseGesture"

    movements: list[str] = field(default_factory=list)
    listed: bool | None = None  # True loaded as a list, False as a bare string, None built in code

    @classmethod
    def _from_arg(cls, arg: Any) -> MouseGesture:
        if isinstance(arg, str):
            return cls([arg], listed=False)
        _require(_is_str_list(arg), "MouseGesture argument is not a string or list of strings")
        return cls(list(arg), listed=True)

    def _arg(self) -> Any:
        return _scalar_or_list(self.movements, self.listed)


# Actions


class KeyPressForm(enum.Enum):
    """The argument shapes diversion.KeyPress.regularize_args accepts."""

    NESTED = "nested"  # [[Control_L, t], click]: Solaar's data() shape; its save writes this for 2+ keys
    PAIR = "pair"  # [Control_L, click]: one key and an action; Solaar's save writes this for one key
    LIST = "list"  # [Control_L, t]: keys, action defaults to click
    SCALAR = "scalar"  # Control_L: one key, action defaults to click


@dataclass
class KeyPress(Component):
    """KeyPress action. `action` None means it was not written (Solaar assumes click)."""

    TYPE: ClassVar[str] = "KeyPress"

    keys: list[str]
    action: str | None = CLICK
    form: KeyPressForm | None = None  # None: built in code, written in Solaar's saved shape

    @classmethod
    def _from_arg(cls, arg: Any) -> KeyPress:
        if isinstance(arg, str):
            return cls([arg], None, KeyPressForm.SCALAR)
        _require(isinstance(arg, list) and arg, "KeyPress argument is not a key name or list")
        if len(arg) == 2 and arg[1] in CLICK_ACTIONS:
            if isinstance(arg[0], str):
                return cls([arg[0]], arg[1], KeyPressForm.PAIR)
            _require(_is_str_list(arg[0]), "KeyPress keys are not strings")
            return cls(list(arg[0]), arg[1], KeyPressForm.NESTED)
        _require(_is_str_list(arg), "KeyPress keys are not strings")
        return cls(list(arg), None, KeyPressForm.LIST)

    def _arg(self) -> Any:
        form = self.form
        if form is None:
            single = len(self.keys) == 1
            if self.action is None:
                form = KeyPressForm.SCALAR if single else KeyPressForm.LIST
            else:
                form = KeyPressForm.PAIR if single else KeyPressForm.NESTED
        if self.action is None:
            ambiguous = len(self.keys) == 2 and self.keys[1] in CLICK_ACTIONS
            if form is KeyPressForm.SCALAR and len(self.keys) == 1:
                return self.keys[0]
            if not ambiguous:
                return list(self.keys)
            # [a, click] would load as key a with action click; spell the action out instead.
            return [list(self.keys), CLICK]
        if form is KeyPressForm.PAIR and len(self.keys) == 1:
            return [self.keys[0], self.action]
        return [list(self.keys), self.action]


@dataclass
class MouseScroll(Component):
    TYPE: ClassVar[str] = "MouseScroll"

    dx: int | float
    dy: int | float
    nested: bool = False  # loaded as [[dx, dy]]

    @classmethod
    def _from_arg(cls, arg: Any) -> MouseScroll:
        nested = isinstance(arg, list) and len(arg) == 1 and isinstance(arg[0], list)
        if nested:
            arg = arg[0]
        _require(
            isinstance(arg, list) and len(arg) == 2 and all(_is_number(a) for a in arg),
            "MouseScroll argument is not two numbers",
        )
        return cls(arg[0], arg[1], nested)

    def _arg(self) -> Any:
        return [[self.dx, self.dy]] if self.nested else [self.dx, self.dy]


@dataclass
class MouseClick(Component):
    """MouseClick action. `count` is a click count or click/depress/release; None means not written (1)."""

    TYPE: ClassVar[str] = "MouseClick"

    button: str
    count: int | str | None = 1
    listed: bool = True

    @classmethod
    def _from_arg(cls, arg: Any) -> MouseClick:
        if isinstance(arg, str):
            return cls(arg, None, listed=False)
        _require(isinstance(arg, list) and len(arg) in (1, 2), "MouseClick argument is not a button or [button, count]")
        _require(isinstance(arg[0], str), "MouseClick button is not a string")
        if len(arg) == 1:
            return cls(arg[0], None, listed=True)
        _require(
            _is_int(arg[1]) or arg[1] in CLICK_ACTIONS,
            f"MouseClick count is not an integer or one of {', '.join(CLICK_ACTIONS)}",
        )
        return cls(arg[0], arg[1], listed=True)

    def _arg(self) -> Any:
        if self.count is None:
            return [self.button] if self.listed else self.button
        return [self.button, self.count]


@dataclass
class Set(Component):
    """Set action: `[device, setting, value...]` or `[device, setting, key, value]`."""

    TYPE: ClassVar[str] = "Set"

    device: str | int | float | bool | None
    setting: str
    values: list[Any] = field(default_factory=list)

    @classmethod
    def _from_arg(cls, arg: Any) -> Set:
        return cls(*_setting_args(arg, cls.TYPE))

    def _arg(self) -> Any:
        return [self.device, self.setting, *self.values]


@dataclass
class Execute(Component):
    TYPE: ClassVar[str] = "Execute"

    args: list[str] = field(default_factory=list)
    listed: bool | None = None  # True loaded as a list, False as a bare string, None built in code

    @classmethod
    def _from_arg(cls, arg: Any) -> Execute:
        if isinstance(arg, str):
            return cls([arg], listed=False)
        _require(_is_str_list(arg), "Execute argument is not a string or list of strings")
        return cls(list(arg), listed=True)

    def _arg(self) -> Any:
        return _scalar_or_list(self.args, self.listed)


@dataclass
class Later(Component):
    """Later action: a delay in seconds, then components to run after it."""

    TYPE: ClassVar[str] = "Later"

    delay: int | float
    components: list[Component] = field(default_factory=list)
    listed: bool | None = None  # True loaded as a list, False as a bare delay, None built in code

    @classmethod
    def _from_arg(cls, arg: Any) -> Later:
        if not isinstance(arg, list):
            _require(_is_number(arg), "Later delay is not a number")
            return cls(arg, listed=False)
        _require(len(arg) >= 1 and _is_number(arg[0]), "Later argument does not start with a delay")
        return cls(arg[0], [component_from_yaml(c) for c in arg[1:]], listed=True)

    def _arg(self) -> Any:
        if self.listed is not True and not self.components:
            return self.delay
        return [self.delay, *(c.to_yaml() for c in self.components)]


COMPONENT_TYPES: dict[str, type[Component]] = {
    cls.TYPE: cls
    for cls in (
        Rule,
        Not,
        Or,
        And,
        Process,
        MouseProcess,
        Feature,
        Report,
        Setting,
        Modifiers,
        Key,
        KeyIsDown,
        Test,
        TestBytes,
        MouseGesture,
        Active,
        Device,
        Host,
        KeyPress,
        MouseScroll,
        MouseClick,
        Set,
        Execute,
        Later,
    )
}
