# SPDX-License-Identifier: GPL-2.0-or-later
"""The lint checks (HL000-HL010). docs/lint.md describes each one and what it does not cover.

Claims about how Solaar evaluates rules are from `.solaar/<tag>/lib/logitech_receiver/diversion.py`
(the same in 1.1.14 and 1.1.20 apart from Feature name lookup):

- The user rules are the components of one Rule, evaluated by `_evaluate`: each component in turn; a
  non-Action that returns None makes the whole evaluation return None at once; a Condition that
  returns a false value ends that Rule (its parent carries on); otherwise the result is the last
  component's. Actions return None. So after a top-level rule that returns None, nothing else runs.
- A rule returns None when it ends in an Action (its conditions all passed), or when a condition
  returns None (Process / MouseProcess with no focus information, Setting with a missing setting).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from heliostat.analysis.context import LintContext
from heliostat.analysis.problems import Fix, Problem, Severity
from heliostat.analysis.solaar_model import (
    ACTION_NAMES,
    SUPPORTED_TAGS,
    load_abort,
    names,
    save_hazards,
)
from heliostat.model import (
    DEPRESS,
    PRESSED,
    RELEASE,
    And,
    Component,
    Device,
    Execute,
    Feature,
    FeatureArgForm,
    Host,
    Key,
    KeyIsDown,
    KeyPress,
    Later,
    Modifiers,
    MouseClick,
    MouseGesture,
    MouseScroll,
    Not,
    Or,
    Raw,
    Report,
    Rule,
    RuleSet,
    Set,
    Test,
    TestBytes,
)
from heliostat.model.ruleset import rule_to_document
from heliostat.rulesfile import RulesParseError, loads
from heliostat.solaar import DivertMode

ACTIONS = (KeyPress, MouseScroll, MouseClick, Set, Execute, Later)
# diversion.MODIFIERS
MODIFIER_NAMES = ("Shift", "Control", "Alt", "Super")
# Test functions that change Solaar state when they match (thumb_wheel_displacement), with a parameter.
STATEFUL_TESTS = ("thumb_wheel_up", "thumb_wheel_down")
# G1-G32, M1-M8 and MR reach rules through the GKEY / MKEYS / MR features, not reprogrammable controls,
# so they are not in a device's control list and their diversion is a different setting.
_EXTRA_KEYS = range(0x1001, 0x1201)


def lint_file(path, context: LintContext | None = None) -> list[Problem]:
    path = Path(path)
    return lint_text(path.read_bytes(), context)


def lint_text(data: str | bytes, context: LintContext | None = None) -> list[Problem]:
    try:
        ruleset = loads(data)
    except RulesParseError as e:
        return [_parse_error(e)]
    return lint_ruleset(ruleset, context)


def lint_ruleset(ruleset: RuleSet, context: LintContext | None = None) -> list[Problem]:
    ctx = context if context is not None else LintContext()
    problems = [Problem(Severity.NOTE, (), "", note) for note in ctx.notes]  # code "": not a check
    problems += _notes(ctx)
    for check in (
        _check_load_aborts,
        _check_undiverted,
        _check_control_names,
        _check_duplicates_and_unreachable,
        _check_depress,
        _check_wayland_process,
        _check_features,
        _check_save_hazards,
    ):
        problems += check(ruleset, ctx)
    problems = [dataclasses.replace(p, rule_path=model_path(ruleset, p.rule_path)) for p in problems]
    return sorted(problems, key=lambda p: (p.rule_path, p.severity.rank, p.code))


def _notes(ctx: LintContext) -> list[Problem]:
    if ctx.devices is None:
        why = ctx.devices_unavailable
    elif not ctx.devices:
        why = "no device is connected"
    else:
        return []
    return [
        Problem(Severity.NOTE, (), "HL001", f"diversion check skipped: {why}"),
        Problem(Severity.NOTE, (), "HL002", f"connected-device part of the control name check skipped: {why}"),
    ]


# Paths


def _children(component: Any) -> list[Component] | None:
    if isinstance(component, (Rule, Or, And, Later)):
        return component.components
    if isinstance(component, Not):
        return [component.component]
    return None


def model_path(ruleset: RuleSet, path: tuple[int, ...]) -> tuple[int, ...]:
    """Cut path back to the deepest component the model holds (a path from the Solaar model can go
    inside a Raw)."""
    if not path or path[0] >= len(ruleset.rules):
        return path[:1]
    node: Any = ruleset.rules[path[0]]
    out = [path[0]]
    for index in path[1:]:
        children = _children(node)
        if children is None or index >= len(children):
            break
        node = children[index]
        out.append(index)
    return tuple(out)


def component_at(ruleset: RuleSet, path: tuple[int, ...]) -> Any:
    node: Any = ruleset.rules[path[0]]
    for index in path[1:]:
        node = _children(node)[index]
    return node


def _walk(components: list[Component], path: tuple[int, ...], negated=False) -> Iterator[tuple[tuple, Any, bool]]:
    """(path, component, under a Not) for every component, depth first, in order."""
    for i, c in enumerate(components):
        p = (*path, i)
        yield p, c, negated
        if isinstance(c, Not):
            yield from _walk([c.component], p, True)
        elif (children := _children(c)) is not None:
            yield from _walk(children, p, negated)


def _rules(ruleset: RuleSet) -> Iterator[tuple[int, Rule]]:
    for i, rule in enumerate(ruleset.rules):
        if isinstance(rule, Rule):
            yield i, rule


def _type_name(component: Any) -> str | None:
    return component.type_name if isinstance(component, Raw) else component.TYPE


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _versions(tags) -> str:
    return " and ".join(f"Solaar {t}" for t in tags)


# HL000


def _parse_error(e: RulesParseError) -> Problem:
    where = f"line {e.line}, column {e.column}" if e.line is not None else "an unknown position"
    n = e.documents_parsed
    return Problem(
        Severity.ERROR,
        (),
        "HL000",
        f"not valid YAML at {where}: {e.message}. Solaar is running only the {_plural(n, 'rule')} before the "
        "error, and its next save of the rules drops everything after it. Heliostat will not edit this file "
        "until the error is fixed.",
    )


# HL009


def _check_load_aborts(ruleset: RuleSet, ctx: LintContext) -> list[Problem]:
    problems = []
    first = True
    for i, rule in enumerate(ruleset.rules):
        document = rule_to_document(rule)
        aborts = {tag: a for tag in SUPPORTED_TAGS if (a := load_abort(document, tag)) is not None}
        if not aborts:
            continue
        applies = [t for t in ctx.tags if t in aborts]
        severity = (
            Severity.ERROR
            if applies and (ctx.version is not None or len(applies) == len(ctx.tags))
            else Severity.WARNING
        )
        tags = applies or list(aborts)
        abort = aborts[tags[0]]
        who = _versions(tags)
        if severity is Severity.WARNING and ctx.version is not None:
            message = f"{who} cannot load this rule ({abort.reason}); the installed Solaar {ctx.version_text} can."
        elif first:
            after = len(ruleset.rules) - i - 1
            message = (
                f"{who} stops loading the rules file here: {abort.reason}. It runs only the "
                f"{_plural(i, 'rule')} before this one, and its next save drops this rule and the "
                f"{_plural(after, 'rule')} after it."
            )
            first = False
        else:
            message = f"{who} also cannot load this rule: {abort.reason}."
        problems.append(Problem(severity, (i, *abort.path), "HL009", message))
    return problems


# HL001, HL002: controls


def _matches_device(device, argument, version) -> bool:
    """diversion.Device.evaluate: unit ID or serial (1.1.20 also codename or name), compared as loaded."""
    candidates = [device.unit_id, device.serial]
    if version is None or version >= (1, 1, 15):
        candidates += [device.codename, device.name]
    return any(c is not None and c == argument for c in candidates)


def _rule_devices(rule: Rule, ctx: LintContext):
    """The online devices a rule can fire for, by the Device conditions at its top level before any action."""
    devices = list(ctx.devices or ())
    for c in rule.components:
        if isinstance(c, ACTIONS):
            break
        if isinstance(c, Device):
            devices = [d for d in devices if _matches_device(d.device, c.device, ctx.version)]
    return devices


def _control_names_for(kind: str, name: str, ctx: LintContext) -> dict[str, int | None]:
    """The control id each applicable tag resolves this name to (None: never matches)."""
    out = {}
    for tag in ctx.tags:
        n = names(tag)
        try:
            if kind == "Key":
                out[tag] = n.key_control(name)
            elif kind == "KeyIsDown":
                out[tag] = n.key_is_down_control(name)
            else:
                out[tag] = n.control_by_name(name)
        except ValueError:
            out[tag] = None  # aborts the load: HL009
    return out


def _printed_names(kind: str, name: str, ctx: LintContext) -> set[str]:
    return {names(t).control_name(c) for t, c in _control_names_for(kind, name, ctx).items() if c is not None}


def _check_undiverted(ruleset: RuleSet, ctx: LintContext) -> list[Problem]:
    if ctx.devices is None:
        return []
    problems = []
    for i, rule in _rules(ruleset):
        devices = _rule_devices(rule, ctx)
        if not devices:
            continue
        for path, c, negated in _walk(rule.components, (i,)):
            if negated:
                continue
            if isinstance(c, (Key, KeyIsDown)):
                problem = _undiverted_key(c, path, devices, ctx)
            elif isinstance(c, MouseGesture):
                problem = _undiverted_gesture(c, path, devices, ctx)
            else:
                continue
            if problem is not None:
                problems.append(problem)
    return problems


def _with_control(devices, printed: set[str]):
    return [(d.device, ctl) for d in devices for ctl in d.controls if ctl.name in printed]


def _divert_fix(device, control, mode: DivertMode) -> Fix | None:
    if not (control.divertable and mode in control.modes and device.serial):
        return None
    return Fix(
        f"set {control.name} on {device.name} to {mode.value}",
        command=("solaar", "config", device.serial, "divert-keys", control.name, mode.value),
    )


def _undiverted_key(c, path, devices, ctx) -> Problem | None:
    ids = _control_names_for(c.TYPE, c.key, ctx)
    if any(i in _EXTRA_KEYS for i in ids.values() if i is not None):
        return None
    found = _with_control(devices, _printed_names(c.TYPE, c.key, ctx))
    # A divertable control with no mode is one whose divert-keys read failed: no claim either way.
    if not found or any(ctl.mode.diverted if ctl.mode else ctl.divertable for _, ctl in found):
        return None
    states = ", ".join(f"{dev.name}: {ctl.mode.value if ctl.mode else 'not divertable'}" for dev, ctl in found)
    name = found[0][1].name
    fixes = [f for dev, ctl in found if (f := _divert_fix(dev, ctl, DivertMode.DIVERTED)) is not None]
    if not fixes:
        return Problem(
            Severity.ERROR,
            path,
            "HL001",
            f"{name} cannot be diverted ({states}), so Solaar never sees it and this {c.TYPE} condition never matches.",
        )
    return Problem(
        Severity.ERROR,
        path,
        "HL001",
        f"{name} is not diverted ({states}), so Solaar never sees it and this {c.TYPE} condition never matches.",
        fixes[0],
    )


def _gesture_ready(ctl) -> bool | None:
    """True if the control is in Mouse Gestures mode, False if not, None if Solaar's data cannot tell."""
    if ctl.mode is None:
        return None if ctl.divertable else False
    if not ctl.mode.diverted:
        return False
    if DivertMode.MOUSE_GESTURES not in ctl.modes:
        return False
    if ctl.saved_mode is None:
        return None
    return ctl.saved_mode is DivertMode.MOUSE_GESTURES


def _undiverted_gesture(c: MouseGesture, path, devices, ctx) -> Problem | None:
    movements = c.movements
    keyed = bool(movements) and not any(names(t).is_movement(movements[0]) for t in ctx.tags)
    if keyed:
        found = _with_control(devices, _printed_names("MouseGesture", movements[0], ctx))
        if not found:
            return None  # HL002
    else:
        found = [(d.device, ctl) for d in devices for ctl in d.controls if DivertMode.MOUSE_GESTURES in ctl.modes]
    if any(_gesture_ready(ctl) is not False for _, ctl in found):
        return None
    fixes = [f for dev, ctl in found if (f := _divert_fix(dev, ctl, DivertMode.MOUSE_GESTURES)) is not None]

    def state(ctl):
        if ctl.mode is None or not ctl.mode.diverted:
            return ctl.mode.value if ctl.mode else "not divertable"
        return ctl.saved_mode.value if ctl.saved_mode else ctl.mode.value

    states = ", ".join(f"{ctl.name} on {dev.name}: {state(ctl)}" for dev, ctl in found)
    if keyed:
        message = (
            f"{movements[0]} is not set to Mouse Gestures ({states}), so this MouseGesture condition never matches."
        )
    elif found:
        message = f"no control is set to Mouse Gestures ({states}), so this MouseGesture condition never matches."
    else:
        message = (
            "no connected device has a control that supports Mouse Gestures, "
            "so this MouseGesture condition never matches."
        )
    fix = fixes[0] if keyed and fixes else None
    if not keyed and fixes:
        fix = Fix("set a control to Mouse Gestures, for example: " + fixes[0].description, command=fixes[0].command)
    return Problem(Severity.ERROR, path, "HL001", message, fix)


def _check_control_names(ruleset: RuleSet, ctx: LintContext) -> list[Problem]:
    problems = []
    for i, rule in _rules(ruleset):
        for path, c, _ in _walk(rule.components, (i,)):
            if isinstance(c, (Key, KeyIsDown)):
                if isinstance(c, KeyIsDown) and c.key.startswith("unknown:"):
                    continue  # resolves only if Solaar created that name earlier; cannot tell
                problem = _unknown_name(c, c.TYPE, c.key, path, ctx, lambda new, c=c: dataclasses.replace(c, key=new))
            elif isinstance(c, MouseGesture):
                problem = None
                for k, m in enumerate(c.movements):
                    if any(names(t).is_movement(m) for t in ctx.tags):
                        continue

                    def replace(new, c=c, k=k):
                        return dataclasses.replace(c, movements=[*c.movements[:k], new, *c.movements[k + 1 :]])

                    problem = _unknown_name(c, "MouseGesture", m, path, ctx, replace)
                    if problem is not None:
                        break
            else:
                continue
            if problem is not None:
                problems.append(problem)
    return problems


def _suggest(kind: str, name: str, tag: str) -> tuple[str, str] | None:
    """(suggested name, why) for a name Solaar <tag> does not resolve."""
    here = names(tag)
    for other in SUPPORTED_TAGS:
        if other == tag:
            continue
        there = names(other)
        control = there.control_by_name(name) if kind == "MouseGesture" else there.key_control(name)
        if control is not None and here.knows(control):
            return here.control_name(control), f"{name!r} is Solaar {other}'s name for it"
    if kind == "MouseGesture":
        control = here.key_control(name)
        if control is not None:
            return here.control_name(control), "MouseGesture compares the name exactly as Solaar prints it"
    for printed in here.printed_names:
        if printed.lower() == name.lower() or printed == name.replace("__", "/").replace("_", " "):
            return printed, "Solaar matches control names case-sensitively"
    return None


def _unknown_name(component, kind, name, path, ctx: LintContext, replace) -> Problem | None:
    resolved = _control_names_for(kind, name, ctx)
    unknown = [t for t, c in resolved.items() if c is None]
    if unknown:
        tag = unknown[0]
        what = "a movement or a control name" if kind == "MouseGesture" else "a control name"
        lost = "matches nothing" if kind == "MouseGesture" else "loads as no key"
        message = f"{name!r} is not {what} Solaar {tag} knows: it {lost}, so this {kind} condition never matches."
        if ctx.version is None:
            severity = Severity.ERROR if len(unknown) == len(resolved) else Severity.WARNING
            if len(unknown) < len(resolved):
                message = (
                    f"{name!r} is not {what} in {_versions(unknown)}, so there this {kind} condition never matches."
                )
        elif ctx.exact:
            severity = Severity.ERROR
        else:
            severity = Severity.WARNING
            message += f" (Checked against Solaar {tag}'s names; the installed Solaar is {ctx.version_text}.)"
        suggestion = _suggest(kind, name, tag)
        fix = None
        if suggestion is not None:
            new, why = suggestion
            fix = Fix(f"use {new!r} ({why})", replacement=replace(new))
        return Problem(severity, path, "HL002", message, fix)
    if ctx.devices is None or not ctx.devices:
        return None
    if any(c in _EXTRA_KEYS for c in resolved.values()):
        return None
    printed = {names(t).control_name(c) for t, c in resolved.items()}
    if _with_control(ctx.devices, printed):
        return None
    shown = sorted(printed)[0]
    message = f"no connected device has a control named {shown!r}."
    fix = None
    if ctx.version is not None:
        here = names(ctx.tags[0])
        for other in SUPPORTED_TAGS:
            if other == here.tag:
                continue
            there = names(other)
            control = there.control_by_name(name) if kind == "MouseGesture" else there.key_control(name)
            if control is None or control == resolved[here.tag]:
                continue
            new = here.control_name(control)
            if _with_control(ctx.devices, {new}):
                message += (
                    f" Solaar {here.tag} calls a different control {shown!r}; {name!r} is Solaar {other}'s name for "
                    f"the control Solaar {here.tag} calls {new!r}, which is connected."
                )
                fix = Fix(f"use {new!r}", replacement=replace(new))
                break
    return Problem(Severity.WARNING, path, "HL002", message, fix)


# HL003, HL004: duplicates and unreachable rules


_STATE_FREE = (Key, MouseGesture, Feature, Report, TestBytes, Device, Host)


def _plain_condition(c: Any) -> bool:
    """A typed condition with no actions or unknown components inside (so it only tests, never acts)."""
    if isinstance(c, Not):
        return _plain_condition(c.component)
    if isinstance(c, (Or, And)):
        return all(_plain_condition(x) for x in c.components)
    return not isinstance(c, (Raw, Rule, *ACTIONS))


def _state_free(c: Any) -> bool:
    """True if the condition's result depends only on the notification and the device that sent it, so
    it is the same wherever it is evaluated in one pass over the rules."""
    if isinstance(c, Not):
        return _state_free(c.component)
    if isinstance(c, (Or, And)):
        return all(_state_free(x) for x in c.components)
    if isinstance(c, Test):
        return not (c.test in STATEFUL_TESTS and c.has_parameter and c.parameter is not None)
    return isinstance(c, _STATE_FREE)


def _has_action(component: Any) -> bool:
    for _, c, _ in _walk([component], ()):
        if isinstance(c, ACTIONS) or (isinstance(c, Raw) and c.type_name in ACTION_NAMES):
            return True
    return False


@dataclasses.dataclass
class _Shape:
    conditions: list[Any]  # normalized prefix conditions
    triggered: bool  # a Key or MouseGesture among them
    stops: bool  # when the conditions all pass, the rule certainly returns None
    state_free: bool
    modifiers_only: bool  # every state-dependent prefix condition is Modifiers
    acts: bool


def _normalize(c: Any, tag: str) -> Any:
    if isinstance(c, Key):
        control = names(tag).key_control(c.key) if not c.key.startswith("unknown:") else None
        return ("Key", control if control is not None else c.key, c.action or PRESSED)
    if isinstance(c, Modifiers):
        return ("Modifiers", tuple(sorted(m for m in c.modifiers if m in MODIFIER_NAMES)))
    if isinstance(c, MouseGesture):
        return ("MouseGesture", tuple(c.movements))
    return (c.TYPE, repr(rule_to_document(Rule([c]))))


def _shape(rule: Rule, tags) -> _Shape:
    prefix = []
    components = rule.components
    k = 0
    while k < len(components) and _plain_condition(components[k]):
        prefix.append(components[k])
        k += 1
    tail = components[k:]
    stops = bool(tail) and isinstance(tail[-1], ACTIONS) and all(isinstance(c, (*ACTIONS, Rule)) for c in tail)
    state_free = all(_state_free(c) for c in prefix)
    modifiers_only = all(_state_free(c) or isinstance(c, Modifiers) for c in prefix)
    # Normalized per tag, so a claim holds whichever applicable Solaar version runs the file.
    conditions = [tuple(_normalize(c, t) for t in tags) for c in prefix]
    triggered = any(isinstance(c, (Key, MouseGesture)) for c in prefix)
    return _Shape(conditions, triggered, stops, state_free, modifiers_only, _has_action(rule))


def _contains_all(big: list, small: list) -> bool:
    return all(s in big for s in small)


def _shadows(a: _Shape, between: list[_Shape]) -> bool:
    """Whether rule a, if its conditions pass, certainly stops processing before a later rule runs.

    Modifiers can change if an action between the two rules presses or releases a key, so a rule
    whose conditions include Modifiers only counts if no rule between them has an action.
    """
    if not a.stops:
        return False
    return a.state_free or (a.modifiers_only and not any(s.acts for s in between))


def _check_duplicates_and_unreachable(ruleset: RuleSet, ctx: LintContext) -> list[Problem]:
    rules = list(_rules(ruleset))
    shapes = {i: _shape(rule, ctx.tags) for i, rule in rules}
    problems = []
    for jpos, (j, _) in enumerate(rules):
        b = shapes[j]
        for ipos in range(jpos):
            i = rules[ipos][0]
            a = shapes[i]
            between = [shapes[rules[p][0]] for p in range(ipos + 1, jpos)]
            if (
                a.triggered
                and b.triggered
                and _contains_all(a.conditions, b.conditions)
                and _contains_all(b.conditions, a.conditions)
            ):
                message = f"rule {j + 1} has the same trigger and conditions as rule {i + 1}."
                if _shadows(a, between):
                    message += (
                        f" Rule {i + 1} always ends in an action, which stops Solaar's processing, "
                        f"so rule {j + 1} never runs."
                    )
                problems.append(Problem(Severity.WARNING, (j,), "HL003", message))
                break
            if _contains_all(b.conditions, a.conditions) and _shadows(a, between):
                what = "conditions" if a.conditions else "no conditions"
                subset = "a subset of its conditions" if a.conditions else "no conditions"
                problems.append(
                    Problem(
                        Severity.WARNING,
                        (j,),
                        "HL004",
                        f"rule {j + 1} can never run: rule {i + 1} has {subset} and always ends in an "
                        f"action, so whenever rule {j + 1}'s {what} pass, Solaar has already stopped "
                        f"processing at rule {i + 1}.",
                    )
                )
                break
    return problems


# HL005


def _check_depress(ruleset: RuleSet, ctx: LintContext) -> list[Problem]:
    problems = []
    for i, rule in _rules(ruleset):
        found = list(_walk(rule.components, (i,)))
        released_keys = {k for _, c, _ in found if isinstance(c, KeyPress) and c.action == RELEASE for k in c.keys}
        released_buttons = {c.button for _, c, _ in found if isinstance(c, MouseClick) and c.count == RELEASE}
        for path, c, _ in found:
            if isinstance(c, KeyPress) and c.action == DEPRESS:
                held = [k for k in c.keys if k not in released_keys]
                if held:
                    keys = ", ".join(held)
                    problems.append(
                        Problem(
                            Severity.WARNING,
                            path,
                            "HL005",
                            f"KeyPress depresses {keys} and nothing in this rule releases "
                            f"{'it' if len(held) == 1 else 'them'}: the key stays held down.",
                            Fix(f"add KeyPress: [{keys}, release] to this rule"),
                        )
                    )
            elif isinstance(c, MouseClick) and c.count == DEPRESS and c.button not in released_buttons:
                problems.append(
                    Problem(
                        Severity.WARNING,
                        path,
                        "HL005",
                        f"MouseClick depresses {c.button} and nothing in this rule releases it: "
                        "the button stays held down.",
                        Fix(f"add MouseClick: [{c.button}, release] to this rule"),
                    )
                )
    return problems


# HL006


def _check_wayland_process(ruleset: RuleSet, ctx: LintContext) -> list[Problem]:
    if not ctx.session.wayland or ctx.session.gnome:
        return []
    problems = []
    for i, rule in _rules(ruleset):
        for path, c, _ in _walk(rule.components, (i,)):
            kind = _type_name(c)
            if kind in ("Process", "MouseProcess"):
                problems.append(
                    Problem(
                        Severity.ERROR,
                        path,
                        "HL006",
                        f"on Wayland outside GNOME, Solaar cannot tell which window has focus: this {kind} condition "
                        "returns no result, which stops this rule and every rule after it (Solaar's built-in rules "
                        "too) each time it is reached.",
                    )
                )
    return problems


# HL007, HL008


def _check_features(ruleset: RuleSet, ctx: LintContext) -> list[Problem]:
    problems = []
    for i, rule in _rules(ruleset):
        for path, c, _ in _walk(rule.components, (i,)):
            if not isinstance(c, Feature):
                continue
            form = c.argument_form
            if form is FeatureArgForm.NONE:
                problems.append(
                    Problem(
                        Severity.ERROR,
                        path,
                        "HL008",
                        "the feature name is already lost (most likely Solaar 1.1.14 saved a spaced feature name "
                        "twice), so this Feature condition never matches. Pick the feature again.",
                    )
                )
            elif form is FeatureArgForm.SPACED:
                new = c.feature.replace(" ", "_")
                old = ctx.version is not None and ctx.version < (1, 1, 15)
                known = all(new in names(t).features for t in SUPPORTED_TAGS)
                if old:
                    message = (
                        f"Solaar {ctx.version_text} loads {c.feature!r} as None (1.1.14 accepts only "
                        f"{new!r}), so this Feature condition never matches."
                    )
                else:
                    message = (
                        f"Solaar 1.1.14 loads {c.feature!r} as None (it accepts only {new!r}), so this Feature "
                        "condition never matches there."
                    )
                if not known:
                    message += f" {new!r} is not a Solaar feature name either."
                problems.append(
                    Problem(
                        Severity.ERROR if old else Severity.WARNING,
                        path,
                        "HL007",
                        message,
                        Fix(f"write the feature as {new!r}", replacement=Feature(new)),
                    )
                )
    return problems


# HL010


def _check_save_hazards(ruleset: RuleSet, ctx: LintContext) -> list[Problem]:
    problems = []
    for i, rule in enumerate(ruleset.rules):
        document = rule_to_document(rule)
        seen = set()
        for tag in ctx.tags:
            for hazard in save_hazards(document, tag):
                key = (hazard.path, hazard.message)
                if key not in seen:
                    seen.add(key)
                    problems.append(Problem(Severity.WARNING, (i, *hazard.path), "HL010", hazard.message))
    return problems
