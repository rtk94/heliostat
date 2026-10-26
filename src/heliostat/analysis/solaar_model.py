# SPDX-License-Identifier: GPL-2.0-or-later
"""What Solaar does with a rules file, per pinned Solaar tag, without importing Solaar.

Everything here mirrors `.solaar/<tag>/lib/logitech_receiver/diversion.py` (and `common.NamedInts`,
`special_keys.CONTROL`), and the conformance tests in tests/conformance/test_lint_claims.py check it
against the real code:

- `SolaarNames`: how the Key, KeyIsDown, MouseGesture and Feature constructors look names up.
- `load_abort`: whether a rule document makes `_load_rule_config` raise (it then keeps only the rules
  before it, and its next save drops the rest).
- `save_hazards`: forms that `_save_config_rule_file` (data() plus convert()) damages.

Both work on the YAML data of one rule document, as Solaar sees it, not on Heliostat's model, and
report component paths in the model's convention (see `Problem.rule_path`). A path can go deeper than
the model does where the model holds a `Raw`; `analysis.lint` cuts it back.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from heliostat.solaar.names import CONTROLS, FEATURES, MOUSE_GESTURE_TESTS, MOVEMENTS

SUPPORTED_TAGS = ("1.1.14", "1.1.20")
SPACED_FEATURES_FROM = (1, 1, 15)  # Feature accepts "THUMB WHEEL" from 1.1.15 (D1 in docs/decisions.md)

# diversion.COMPONENTS keys; diversion.Action subclasses.
COMPONENT_NAMES = frozenset(
    "Rule Not Or And Process MouseProcess Feature Report Setting Modifiers Key KeyIsDown Test TestBytes "
    "MouseGesture Active Device Host KeyPress MouseScroll MouseClick Set Execute Later".split()
)
ACTION_NAMES = frozenset("KeyPress MouseScroll MouseClick Set Execute Later".split())
CLICK_ACTIONS = ("click", "depress", "release")

_SCALAR = (int, str, float)  # what convert() collapses a one-item list to (bool is an int)
_FALLBACK_NAME = re.compile(r"unknown:([0-9A-F]{4,})")


def tag_for_version(version: tuple[int, int, int]) -> str:
    """The pinned tag whose names and behavior lint uses for an installed Solaar version.

    Only 1.1.14 and 1.1.20 are checked against source. Versions in between and after use 1.1.20's,
    and `exact_tag` is False for them, so callers can say so instead of claiming certainty.
    """
    return "1.1.14" if version < SPACED_FEATURES_FROM else "1.1.20"


def exact_tag(version: tuple[int, int, int]) -> bool:
    return ".".join(map(str, version)) in SUPPORTED_TAGS


def _readable(key: str) -> str:
    """NamedInts.__init__: the name a CONTROL entry prints as."""
    return key.replace("__", "/").replace("_", " ")


class SolaarNames:
    """Name lookups as one Solaar tag does them.

    CONTROL is a NamedInts. `name in CONTROL` matches a NamedInts key (`Back_Button`) exactly or a
    printed name (`Back Button`) ignoring case; `CONTROL[name]` matches the key exactly or the printed
    name exactly, else gives None. So `back button` passes the membership test and then looks up None.
    """

    def __init__(self, tag: str):
        self.tag = tag
        self._keys = CONTROLS[tag]
        ordered = sorted(self._keys.items(), key=lambda kv: kv[1])  # NamedInts keeps values sorted by int
        self._printed: dict[str, int] = {}
        for key, value in ordered:
            self._printed.setdefault(_readable(key), value)
        self._printed_lower = {name.lower() for name in self._printed}
        self._by_id = {value: _readable(key) for key, value in ordered}
        self.features = FEATURES[tag]
        self.movements = MOVEMENTS[tag]
        self.mouse_gesture_tests = MOUSE_GESTURE_TESTS[tag]

    def _contains(self, name: str) -> bool:
        return name in self._keys or name.lower() in self._printed_lower

    def _lookup(self, name: str) -> int | None:
        if name in self._keys:
            return self._keys[name]
        return self._printed.get(name)

    def key_control(self, key: Any) -> int | None:
        """The control a Key condition matches, or None where Solaar uses key 0 or None (never matches).

        Raises ValueError where Solaar's own lookup does (an `unknown:` name whose last 4 characters
        are not hex), which aborts the load.
        """
        if not isinstance(key, str):
            return None
        if self._contains(key):
            return self._lookup(key)
        if key.startswith("unknown:"):
            return int(key[-4:], 16)
        return None

    def key_is_down_control(self, key: Any) -> int | None:
        """The control a KeyIsDown condition tests, or None. KeyIsDown has no `unknown:` lookup."""
        if isinstance(key, str) and self._contains(key):
            return self._lookup(key)
        return None

    def knows(self, control: int) -> bool:
        """True if CONTROL names this control number (rather than falling back to `unknown:XXXX`)."""
        return control in self._by_id

    @property
    def printed_names(self) -> tuple[str, ...]:
        return tuple(self._printed)

    def control_name(self, control: int) -> str:
        """str(CONTROL[control]): the printed name, or the fallback `unknown:XXXX`."""
        return self._by_id.get(control, f"unknown:{control:04X}")

    def control_by_name(self, name: str) -> int | None:
        """The control whose printed name (`control_name`) is exactly `name`. MouseGesture compares names
        this way, so `Back_Button` or `back button` never match there."""
        if name in self._printed:
            return self._printed[name]
        m = _FALLBACK_NAME.fullmatch(name)
        if m and int(m[1], 16) not in self._by_id:
            return int(m[1], 16)
        return None

    def is_movement(self, name: Any) -> bool:
        return name in self.movements

    def feature(self, argument: str) -> int | None:
        """The feature a Feature condition with this string argument matches; None if it never matches."""
        name = argument if self.tag == "1.1.14" else argument.replace(" ", "_")
        return self.features.get(name)


_NAMES = {tag: SolaarNames(tag) for tag in SUPPORTED_TAGS}


def names(tag: str) -> SolaarNames:
    return _NAMES[tag]


def _one_key(item: Any) -> tuple[str, Any] | None:
    """(type, argument) if RuleComponent.compile builds a component from item, else None (Condition())."""
    if isinstance(item, dict) and len(item) == 1:
        ((key, value),) = item.items()
        if key in COMPONENT_NAMES:
            return key, value
    return None


def _not_operand(arg: Any) -> Any:
    return arg[0] if isinstance(arg, list) and len(arg) == 1 else arg


def _later_parts(arg: Any) -> tuple[bool, list[Any]]:
    """(delay valid, the items after the delay). Later compiles its components only for a valid delay."""
    args = arg if isinstance(arg, list) else [arg]
    if not args:
        return False, []
    delay = args[0]
    return isinstance(delay, (int, float)) and 0.01 <= delay <= 100, args[1:]


# Load aborts


@dataclass(frozen=True)
class LoadAbort:
    path: tuple[int, ...]
    reason: str


class _Abort(Exception):
    def __init__(self, path: tuple[int, ...], reason: str):
        self.path, self.reason = path, reason


def _items(args: Any, path: tuple[int, ...], what: str) -> list[Any]:
    """`for a in args`, as Rule, Or and And iterate their argument (a string gives its characters)."""
    try:
        return list(args)
    except TypeError:
        raise _Abort(path, f"{what} is {_show(args)}, not a list") from None


def _hashable(value: Any) -> bool:
    try:
        hash(value)
    except TypeError:
        return False
    return True


def _show(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return "a list" if isinstance(value, list) else "a mapping"
    return repr(value)


def load_abort(document: Any, tag: str) -> LoadAbort | None:
    """Where and why Solaar <tag> raises while loading this rule document, or None if it loads."""
    try:
        for i, item in enumerate(_items(document, (), "the rule document")):
            _load_component(item, (i,), tag)
    except _Abort as e:
        return LoadAbort(e.path, e.reason)
    return None


def _load_component(item: Any, path: tuple[int, ...], tag: str) -> None:
    compiled = _one_key(item)
    if compiled is None:
        return  # Condition(): always false, loads fine
    kind, arg = compiled
    loader = _LOADERS.get(kind)
    if loader is not None:
        loader(arg, path, tag)


def _load_rule(arg, path, tag):
    for i, item in enumerate(_items(arg, path, "the argument")):
        _load_component(item, (*path, i), tag)


def _load_not(arg, path, tag):
    _load_component(_not_operand(arg), (*path, 0), tag)


def _load_feature(arg, path, tag):
    if tag == "1.1.14":
        # SupportedFeature[feature] catches only KeyError; a list or mapping raises TypeError.
        if not _hashable(arg):
            raise _Abort(path, f"the Feature argument is {_show(arg)}, not a feature name")
    elif not isinstance(arg, str):
        # 1.1.15+: SupportedFeature[feature.replace(" ", "_")] raises AttributeError on a non-string.
        raise _Abort(path, f"the Feature argument is {_show(arg)}, not a feature name")


def _load_modifiers(arg, path, tag):
    for k in _items([arg] if isinstance(arg, str) else arg, path, "the Modifiers argument"):
        if not _hashable(k):
            raise _Abort(path, f"a Modifiers item is {_show(k)}, not a modifier name")


def _load_key(arg, path, tag):
    if not arg or not isinstance(arg, (list, str)):
        return
    key = arg if isinstance(arg, str) else arg[0]
    try:
        names(tag).key_control(key)
    except ValueError:
        raise _Abort(path, f"the Key name {key!r} starts with 'unknown:' but does not end in 4 hex digits") from None


def _load_test(arg, path, tag):
    test = [arg] if isinstance(arg, str) else arg
    if not isinstance(test, list) or all(isinstance(t, int) for t in test):
        return  # warning only, or converted to TestBytes
    if not _hashable(test[0]):
        raise _Abort(path, f"the Test name is {_show(test[0])}")
    if test[0] in names(tag).mouse_gesture_tests:
        # Test converts these to MouseGesture with MOUSE_GESTURE_TESTS[0][test], which raises KeyError.
        raise _Abort(path, f"the deprecated mouse movement test {test[0]!r} makes Solaar's load raise")


def _load_mouse_gesture(arg, path, tag):
    _items([arg] if isinstance(arg, str) else arg, path, "the MouseGesture argument")


def _load_key_press(arg, path, tag):
    args = arg if isinstance(arg, list) else [arg]
    keys = args
    if len(args) == 2 and args[1] in CLICK_ACTIONS:
        keys = [args[0]] if isinstance(args[0], str) else args[0]
    if not isinstance(keys, list):
        # KeyPress logs this case through a misspelled attribute (self.keys_names): AttributeError.
        raise _Abort(path, f"the KeyPress keys are {_show(keys)}, not key names")
    for k in keys:
        if not _hashable(k):
            raise _Abort(path, f"a KeyPress key is {_show(k)}, not a key name")


def _first_if_single(arg, path, what):
    """`len(args) == 1 and isinstance(args[0], list)`, as MouseScroll and MouseClick start."""
    try:
        if len(arg) == 1:
            arg[0]
    except (TypeError, KeyError, IndexError):
        raise _Abort(path, f"the {what} argument is {_show(arg)}") from None


def _load_mouse_scroll(arg, path, tag):
    _first_if_single(arg, path, "MouseScroll")


def _load_mouse_click(arg, path, tag):
    _first_if_single(arg, path, "MouseClick")
    args = arg[0] if len(arg) == 1 and isinstance(arg[0], list) else arg
    args = args if isinstance(args, list) else [args]
    if not args:
        raise _Abort(path, "the MouseClick argument is an empty list")
    if len(args) >= 2:
        try:
            int(args[1])
        except (ValueError, TypeError):
            pass  # caught by MouseClick
        except Exception as e:  # e.g. OverflowError for .inf
            raise _Abort(path, f"the MouseClick count {args[1]!r} raises {type(e).__name__}") from None


def _load_execute(arg, path, tag):
    # Execute's argument check is a generator expression; creating it iterates the argument.
    _items([arg] if isinstance(arg, str) else arg, path, "the Execute argument")


def _load_later(arg, path, tag):
    valid, items = _later_parts(arg)
    if valid:
        for i, item in enumerate(items):
            _load_component(item, (*path, i), tag)


_LOADERS = {
    "Rule": _load_rule,
    "Or": _load_rule,
    "And": _load_rule,
    "Not": _load_not,
    "Feature": _load_feature,
    "Modifiers": _load_modifiers,
    "Key": _load_key,
    "Test": _load_test,
    "MouseGesture": _load_mouse_gesture,
    "KeyPress": _load_key_press,
    "MouseScroll": _load_mouse_scroll,
    "MouseClick": _load_mouse_click,
    "Execute": _load_execute,
    "Later": _load_later,
}


# Save hazards


@dataclass(frozen=True)
class SaveHazard:
    path: tuple[int, ...]
    message: str


def _has_one_scalar_list(value: Any) -> bool:
    """True if convert() would collapse some list inside value."""
    if isinstance(value, list):
        return (len(value) == 1 and isinstance(value[0], _SCALAR)) or any(_has_one_scalar_list(v) for v in value)
    if isinstance(value, dict):
        return any(_has_one_scalar_list(v) for v in value.values())
    return False


def save_hazards(document: Any, tag: str) -> list[SaveHazard]:
    """What Solaar <tag>'s save (data(), then convert()) would damage in a document that loads.

    Only the cases listed in docs/solaar-reference.md ("Save hazards") are reported.
    """
    if load_abort(document, tag) is not None:
        return []
    return list(_hazards_in_items(list(document), (), tag))


def _hazards_in_items(items: list[Any], path: tuple[int, ...], tag: str) -> Iterator[SaveHazard]:
    for i, item in enumerate(items):
        yield from _hazards(item, (*path, i), tag)


def _hazards(item: Any, path: tuple[int, ...], tag: str) -> Iterator[SaveHazard]:
    compiled = _one_key(item)
    if compiled is None:
        yield SaveHazard(
            path,
            "Solaar loads this as an empty condition that has no saved form, so saving from Solaar's rule "
            "editor fails and writes nothing",
        )
        return
    kind, arg = compiled
    if kind in ("Rule", "Or", "And"):
        yield from _hazards_in_items(list(arg), path, tag)
    elif kind == "Not":
        yield from _hazards(_not_operand(arg), (*path, 0), tag)
    elif kind == "Later":
        valid, items = _later_parts(arg)
        if valid:
            yield from _hazards_in_items(items, path, tag)
        elif items:
            yield SaveHazard(
                path,
                "the Later delay is not a number from 0.01 to 100, so Solaar keeps delay 0 and no actions; "
                f"its save writes 'Later: 0' and deletes the {len(items)} component(s) inside",
            )
    elif kind in ("Device", "Active", "Host"):
        if _has_one_scalar_list(arg):
            yield SaveHazard(
                path,
                f"Solaar's save writes the one-item list in this {kind} argument as a bare value, which "
                f"changes what it matches (the list as written never matches)",
            )
    elif kind in ("Setting", "Set"):
        if not (isinstance(arg, list) and len(arg) > 2):
            if arg != []:
                yield SaveHazard(
                    path,
                    f"the {kind} argument is not a list of at least 3 items, so Solaar keeps an empty one; "
                    f"its save writes '{kind}: []' and deletes what was there",
                )
        elif _has_one_scalar_list(arg):
            yield SaveHazard(
                path, f"Solaar's save writes the one-item list in this {kind} argument as a bare value, changing it"
            )
    elif kind == "Execute":
        args = [arg] if isinstance(arg, str) else arg
        if isinstance(args, dict):
            yield SaveHazard(
                path, "Solaar's save cannot write an Execute mapping, so saving from its rule editor fails"
            )
        elif len(args) == 1 and isinstance(args[0], (int, float)):
            yield SaveHazard(
                path,
                "Solaar's save writes this one-item list as a bare number, and its next load then raises on "
                "it, dropping this rule and every rule after it",
            )
        elif any(_has_one_scalar_list(a) for a in args):
            yield SaveHazard(path, "Solaar's save writes a one-item list inside this Execute command as a bare value")
    elif kind in ("Test", "TestBytes"):
        yield from _test_hazards(kind, arg, path)
    elif kind == "Key":
        yield from _key_hazards(arg, path, tag)
    elif kind == "KeyIsDown":
        yield from _key_is_down_hazards(arg, path, tag)
    elif kind == "Feature":
        yield from _feature_hazards(arg, path, tag)


def _test_hazards(kind, arg, path):
    test = [arg] if kind == "Test" and isinstance(arg, str) else arg
    if isinstance(test, list) and all(isinstance(t, int) for t in test):  # Test of integers is TestBytes
        if len(test) == 1:
            yield SaveHazard(
                path,
                "Solaar's save writes this one-integer list as 'TestBytes: <n>', and its next save then fails "
                "on that (TestBytes copies its argument as a list)",
            )
    elif kind == "TestBytes":
        if not isinstance(arg, (list, str)):
            yield SaveHazard(
                path, f"Solaar's save cannot write TestBytes {_show(arg)}, so saving from its rule editor fails"
            )
    elif isinstance(test, list) and len(test) > 1 and _has_one_scalar_list(test[1]):
        yield SaveHazard(path, "Solaar's save writes the one-item list Test parameter as a bare value, changing it")


def _key_hazards(arg, path, tag):
    if not arg or not isinstance(arg, (list, str)):
        return
    key = arg if isinstance(arg, str) else arg[0]
    if isinstance(key, str) and names(tag).key_control(key) is None:
        yield SaveHazard(
            path,
            f"Solaar {tag} does not know the control {key!r}; its save writes it as "
            f"{_lost_key(key, tag)!r} and the name is lost",
        )


def _key_is_down_hazards(arg, path, tag):
    if isinstance(arg, str) and arg.startswith("unknown:"):
        return  # resolves only if something else made Solaar create that name first; cannot tell
    if names(tag).key_is_down_control(arg) is not None:
        return
    lost = _lost_key(arg, tag)
    if isinstance(arg, str):
        yield SaveHazard(path, f"Solaar {tag} does not know the control {arg!r}; its save writes it as {lost!r}")
    else:
        yield SaveHazard(
            path,
            f"KeyIsDown takes one control name, not {_show(arg)}: Solaar ignores this argument and its save "
            f"writes KeyIsDown: {lost!r}, deleting what was there",
        )


def _lost_key(key, tag):
    """What Key / KeyIsDown data() writes for a name that does not resolve: str(0), or str(None) where the
    membership test passes but the lookup fails (a case mismatch)."""
    n = names(tag)
    return "None" if isinstance(key, str) and n._contains(key) else "0"


def _feature_hazards(arg, path, tag):
    if not isinstance(arg, str) or arg == "None":
        return  # HL009 (load aborts on 1.1.15+) and HL008 cover these
    n = names(tag)
    if tag == "1.1.14":
        if " " in arg:
            return  # HL007: already loads as None here
        if arg in n.features and "_" in arg:
            yield SaveHazard(
                path,
                f"Solaar 1.1.14's save writes this as '{arg.replace('_', ' ')}', which 1.1.14 then loads as "
                "None: after a save from Solaar's rule editor the condition never matches (and the next save "
                "writes 'Feature: None')",
            )
            return
    if n.feature(arg) is None:
        yield SaveHazard(path, f"Solaar {tag} does not know the feature {arg!r}; its save writes 'Feature: None'")
