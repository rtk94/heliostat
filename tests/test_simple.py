# SPDX-License-Identifier: GPL-2.0-or-later
"""Simple rules: recognize, generate (byte-identical round trip), describe."""

from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from heliostat.model import (
    PRESSED,
    RELEASED,
    Device,
    Execute,
    Key,
    KeyPress,
    KeyPressForm,
    Modifiers,
    MouseClick,
    MouseGesture,
    MouseScroll,
    Or,
    Process,
    Rule,
    RuleSet,
    Set,
    component_from_yaml,
)
from heliostat.rulesfile import RulesParseError, dumps, load, loads
from heliostat.simple import (
    TRIGGER_KEY_ACTIONS,
    GestureTrigger,
    KeyTrigger,
    NotSimple,
    SimpleRule,
    describe,
    generate,
    not_simple_reason,
    recognize,
)
from tests.conformance.test_property import CONTROLS, MODIFIER_NAMES, MOVEMENTS, _components, _leaves

FIXTURES = Path(__file__).parent / "fixtures" / "rules"


def _parses(path):
    try:
        load(path)
    except RulesParseError:
        return False
    return True


PARSEABLE = [f for f in sorted(FIXTURES.glob("*.yaml")) if _parses(f)]


def _rule(text: str) -> Rule:
    (rule,) = RuleSet.from_yaml([yaml.safe_load(text)]).rules
    assert isinstance(rule, Rule)
    return rule


def _text(rule) -> str:
    return dumps(RuleSet([rule]))


def assert_regenerates(rule):
    simple = recognize(rule)
    assert simple is not None, not_simple_reason(rule)
    assert _text(generate(simple)) == _text(rule)
    return simple


# Fixtures


@pytest.mark.parametrize("fixture", PARSEABLE, ids=lambda p: p.stem)
def test_recognized_fixture_rules_regenerate_byte_identically(fixture):
    for rule in load(fixture).rules:
        if recognize(rule) is not None:
            assert_regenerates(rule)


def test_simple_shapes_fixture():
    rules = load(FIXTURES / "simple-shapes.yaml").rules
    assert [not_simple_reason(r) for r in rules[:2]] == ["Or condition", "Or condition"]
    for rule in rules[2:]:
        assert_regenerates(rule)
    assert [recognize(r) for r in rules] == [
        None,
        None,
        SimpleRule(
            KeyTrigger("Smart Shift", RELEASED), [MouseScroll(0, -3)], device=12345678, modifiers=[], process="firefox"
        ),
        SimpleRule(GestureTrigger(["Mouse Gesture Button"]), [Execute(["notify-send", "gesture tap"], listed=True)]),
        SimpleRule(
            GestureTrigger(["Mouse Gesture Button", "Mouse Up-left", "Middle Button"]),
            [
                Set(None, "divert-keys", ["Smart Shift", "Diverted"]),
                KeyPress(["Super_L"], "depress", KeyPressForm.PAIR),
                KeyPress(["Super_L"], "release", KeyPressForm.NESTED),
            ],
            device="198E3EB8",
        ),
        SimpleRule(KeyTrigger("Back Button", PRESSED), [KeyPress(["XF86_AudioMute"], None, KeyPressForm.SCALAR)]),
    ]
    assert isinstance(recognize(rules[2]).device, int)


# recognize

KEYPRESS_A = KeyPress(["a"], None, KeyPressForm.SCALAR)
EXECUTE_LS = Execute(["ls"], listed=False)


@pytest.mark.parametrize(
    ("text", "simple"),
    [
        ("[Key: Back Button, KeyPress: a]", SimpleRule(KeyTrigger("Back Button"), [KEYPRESS_A])),
        ("[Key: [Back Button], KeyPress: a]", SimpleRule(KeyTrigger("Back Button"), [KEYPRESS_A])),
        ("[Key: [X, released], Execute: ls]", SimpleRule(KeyTrigger("X", RELEASED), [EXECUTE_LS])),
        ("[MouseGesture: Mouse Up, Execute: ls]", SimpleRule(GestureTrigger(["Mouse Up"]), [EXECUTE_LS])),
        (
            "[Modifiers: Shift, Process: kate, Key: X, Device: 5, Set: [null, dpi, 800]]",
            SimpleRule(KeyTrigger("X"), [Set(None, "dpi", [800])], device=5, modifiers=["Shift"], process="kate"),
        ),
        # Shapes the typed model accepts but lint flags (unknown names) are still simple.
        ("[Key: Not A Key, Modifiers: [Hyper], MouseClick: nope]", None),
    ],
)
def test_recognize(text, simple):
    rule = _rule(text)
    result = assert_regenerates(rule)
    if simple is not None:
        assert result == simple


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("[KeyPress: a]", "no Key or MouseGesture trigger"),
        ("[Key: X]", "no action"),
        ("[Key: X, Key: Y, KeyPress: a]", "more than one Key or MouseGesture trigger condition"),
        ("[Key: X, MouseGesture: Mouse Up, KeyPress: a]", "more than one Key or MouseGesture trigger condition"),
        ("[Key: X, Process: a, Process: b, KeyPress: a]", "more than one Process condition"),
        ("[Key: X, KeyPress: a, Process: b]", "Process condition after an action"),
        ("[Key: X, KeyPress: a, Later: [1, KeyPress: b]]", "Later action after an action"),
        ("[Key: X, Rule: [KeyPress: a]]", "nested rule"),
        ("[Key: X, Feature: CROWN, KeyPress: a]", "Feature condition"),
        ("[Key: X, MouseProcess: kate, KeyPress: a]", "MouseProcess condition"),
        ("[Key: X, Not: {Process: kate}, KeyPress: a]", "Not condition"),
        ("[Key: X, Device: [MX], KeyPress: a]", "unrecognized Device component"),
        ("[Key: X, MouseScroll: 5]", "unrecognized MouseScroll component"),
        ("[MouseGesture: [], KeyPress: a]", "MouseGesture with no movements"),
        ("[Or: [Key: [X, pressed], Key: [X, released]], KeyPress: a]", "Or condition"),
        ("[Or: [Key: [X, released], Key: [X]], KeyPress: a]", "Or condition"),
        ("[Or: [Key: [X, pressed], Key: [Y, released]], KeyPress: a]", "Or condition"),
        ("[Or: [Key: [X, pressed], Key: [X, pressed]], KeyPress: a]", "Or condition"),
        ("[Or: [Key: [X, pressed], Key: [X, released], Key: Z], KeyPress: a]", "Or condition"),
        ("[]", "no Key or MouseGesture trigger"),
    ],
)
def test_not_simple(text, reason):
    rule = _rule(text)
    assert recognize(rule) is None
    assert not_simple_reason(rule) == reason


def test_not_simple_non_rules():
    assert not_simple_reason(component_from_yaml({"Process": [1]})) == "not a rule"
    assert not_simple_reason(RuleSet.from_yaml([{"Key": "X"}]).rules[0]) == "not a rule"
    assert not_simple_reason(Key("X")) == "a Key component, not a rule"


def test_recognize_copies():
    rule = _rule("[Key: X, KeyPress: a]")
    simple = recognize(rule)
    simple.actions[0].keys.append("b")
    simple.written["trigger"].key = "Y"
    assert _text(rule) == _text(_rule("[Key: X, KeyPress: a]"))


# generate


def test_generate_new_rule_in_solaar_shape():
    simple = SimpleRule(
        KeyTrigger("Back Button", RELEASED),
        [KeyPress(["Control_L", "Tab"]), KeyPress(["a"]), MouseClick("left", 2), Execute(["xflock4"])],
        device=12345678,
        modifiers=["Control"],
        process="firefox",
    )
    assert _text(generate(simple)) == (
        "%YAML 1.3\n"
        "---\n"
        "- Key: [Back Button, released]\n"
        "- Device: 12345678\n"
        "- Modifiers: Control\n"
        "- Process: firefox\n"
        "- KeyPress:\n"
        "  - [Control_L, Tab]\n"
        "  - click\n"
        "- KeyPress:\n"
        "  - a\n"
        "  - click\n"
        "- MouseClick: [left, 2]\n"
        "- Execute: xflock4\n"
        "...\n"
    )


def test_generate_gesture():
    simple = SimpleRule(GestureTrigger(["Mouse Up"]), [MouseScroll(0, 1)], modifiers=["Shift", "Alt"])
    assert _text(generate(simple)) == (
        "%YAML 1.3\n---\n- MouseGesture: Mouse Up\n- Modifiers: [Shift, Alt]\n- MouseScroll: [0, 1]\n...\n"
    )


def test_edit_keeps_other_conditions_as_written():
    rule = _rule("[Modifiers: [Shift], Key: Back Button, Device: 5, Execute: [ls]]")
    simple = recognize(rule)
    simple.modifiers = ["Shift", "Control"]
    simple.process = "kate"
    assert _text(generate(simple)) == _text(
        _rule("[Modifiers: [Shift, Control], Key: Back Button, Device: 5, Process: kate, Execute: [ls]]")
    )


def test_edit_trigger_rewrites_only_the_trigger():
    simple = recognize(_rule("[Key: Back Button, Modifiers: [Shift], KeyPress: a]"))
    simple.trigger.action = RELEASED
    assert _text(generate(simple)) == _text(_rule("[Key: [Back Button, released], Modifiers: [Shift], KeyPress: a]"))
    # Back to the loaded value: written as loaded again.
    simple.trigger = KeyTrigger("Back Button", PRESSED)
    assert _text(generate(simple)) == _text(_rule("[Key: Back Button, Modifiers: [Shift], KeyPress: a]"))
    simple.trigger = GestureTrigger(["Mouse Up"])
    assert _text(generate(simple)) == _text(_rule("[MouseGesture: Mouse Up, Modifiers: [Shift], KeyPress: a]"))


def test_removed_condition_is_dropped():
    simple = recognize(_rule("[Key: X, Device: 5, Process: kate, KeyPress: a]"))
    simple.device = None
    assert _text(generate(simple)) == _text(_rule("[Key: X, Process: kate, KeyPress: a]"))


def test_device_value_is_type_strict():
    simple = recognize(_rule("[Key: X, Device: 1, KeyPress: a]"))
    simple.device = True
    assert generate(simple).components[1] == Device(True)
    simple.device = "1"
    assert _text(generate(simple)) == _text(_rule("[Key: X, Device: '1', KeyPress: a]"))


@pytest.mark.parametrize(
    "simple",
    [
        SimpleRule(KeyTrigger("X"), []),
        SimpleRule(KeyTrigger("X", "down"), [Execute(["ls"])]),
        SimpleRule(KeyTrigger(5), [Execute(["ls"])]),
        SimpleRule(GestureTrigger([]), [Execute(["ls"])]),
        SimpleRule(Key("X"), [Execute(["ls"])]),
        SimpleRule(KeyTrigger("X"), [Process("kate")]),
        SimpleRule(KeyTrigger("X"), [Execute(["ls"])], device=[1]),
        SimpleRule(KeyTrigger("X"), [Execute(["ls"])], modifiers=[1]),
        SimpleRule(KeyTrigger("X"), [Execute(["ls"])], process=1),
    ],
)
def test_generate_rejects_invalid(simple):
    with pytest.raises(NotSimple):
        generate(simple)


# describe


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "[Key: [Back Button, pressed], KeyPress: [[Control_L, Tab], click]]",
            "When Back Button is pressed: press Ctrl+Tab",
        ),
        (
            "[Key: [Back Button, released], KeyPress: [Super_L, depress]]",
            "When Back Button is released: hold down Super",
        ),
        (
            "[Key: X, KeyPress: [XF86_AudioMute, release]]",
            "When X is pressed: release Mute",
        ),
        (
            "[Key: Back Button, Device: MX Master 3, Modifiers: [Control, Shift], Process: firefox, KeyPress: t]",
            "When Back Button on MX Master 3 is pressed with Ctrl+Shift held in firefox: press T",
        ),
        ("[Key: X, Modifiers: [], KeyPress: F5]", "When X is pressed with no modifier held: press F5"),
        (
            "[MouseGesture: [Back Button, Mouse Up, Mouse Down-left], Execute: [notify-send, hi there]]",
            "When Back Button is held and you move up, then move down-left: run notify-send 'hi there'",
        ),
        (
            "[MouseGesture: [Mouse Up, Middle Button], Device: 5, Execute: []]",
            "When a gesture button on 5 is held and you move up, then press Middle Button: run nothing",
        ),
        (
            "[MouseGesture: Back Button, MouseClick: [left, 2]]",
            "When Back Button is pressed and released without moving the mouse: double-click the left button",
        ),
        (
            "[Key: X, MouseClick: middle, MouseClick: [button9, 3], MouseClick: [right, depress],"
            " MouseClick: [x, release]]",
            "When X is pressed: click the middle button, then click the button 9 3 times, "
            "then hold down the right button, then release the x",
        ),
        (
            "[Key: X, MouseScroll: [0, 1], MouseScroll: [-2, 0], MouseScroll: [1.5, -1], MouseScroll: [0, 0]]",
            "When X is pressed: scroll up 1, then scroll left 2, then scroll down 1 and right 1.5, then scroll by 0",
        ),
        (
            "[Key: X, Set: [null, divert-keys, Smart Shift, Diverted], Set: [198E3EB8, hires-smooth-invert, true]]",
            "When X is pressed: set divert-keys for Smart Shift to Diverted, "
            "then set hires-smooth-invert to true on 198E3EB8",
        ),
    ],
)
def test_describe(text, expected):
    assert describe(recognize(_rule(text))) == expected


def test_describe_device_names():
    simple = recognize(_rule("[Key: Back Button, Device: 12345678, Set: [12345678, dpi, 800], KeyPress: a]"))
    names = {12345678: "MX Master 3"}
    assert describe(simple, names) == (
        "When Back Button on MX Master 3 is pressed: set dpi to 800 on MX Master 3, then press A"
    )
    assert describe(simple, {"12345678": "wrong type"}).startswith("When Back Button on 12345678 ")


# Properties

names = st.sampled_from(CONTROLS) | st.text(max_size=8)
device_ids = st.text(max_size=8) | st.integers() | st.floats(allow_nan=False) | st.booleans()


def _listed_strings(cls, elements):
    """A list-argument component in each loaded form: list (any length), or a bare single item."""
    return st.builds(cls, st.lists(elements, min_size=1, max_size=3), st.sampled_from([True, None])) | elements.map(
        lambda x: cls([x], False)
    )


@st.composite
def pressed_released_or(draw):
    """The Or of a Key pressed and released: not a simple trigger."""
    key = draw(names)
    pressed = Key(key, draw(st.sampled_from([None, PRESSED])), draw(st.booleans()))
    released = Key(key, RELEASED)
    return Or(draw(st.permutations([pressed, released])))


triggers = st.one_of(
    st.builds(Key, names, st.sampled_from([None, PRESSED, RELEASED]), st.booleans()),
    _listed_strings(MouseGesture, st.sampled_from(MOVEMENTS) | names),
)
optional_conditions = {
    "device": st.builds(Device, device_ids),
    "modifiers": _listed_strings(Modifiers, st.sampled_from(MODIFIER_NAMES)) | st.just(Modifiers([], listed=True)),
    "process": st.builds(Process, st.text(max_size=8)),
}
actions = _leaves(canonical=False, actions_only=True)


@st.composite
def simple_shaped_rules(draw):
    """Rules in the simple shape, in every argument form and condition order."""
    present = draw(st.lists(st.sampled_from(sorted(optional_conditions)), unique=True))
    conditions = [draw(triggers), *(draw(optional_conditions[name]) for name in present)]
    conditions = draw(st.permutations(conditions))
    return Rule([*conditions, *draw(st.lists(actions, min_size=1, max_size=3))])


@st.composite
def near_simple_rules(draw):
    """Simple-shaped rules with one component inserted, removed or replaced."""
    components = list(draw(simple_shaped_rules()).components)
    other = draw(
        _components(canonical=False) | triggers | pressed_released_or() | st.one_of(*optional_conditions.values())
    )
    i = draw(st.integers(0, len(components)))
    match draw(st.sampled_from(["insert", "remove", "replace"])):
        case "insert":
            components.insert(i, other)
        case "remove" if i < len(components):
            del components[i]
        case _ if i < len(components):
            components[i] = other
    return Rule(components)


@settings(max_examples=500)
@given(simple_shaped_rules())
def test_simple_shaped_rules_are_recognized_and_regenerate(rule):
    assert_regenerates(rule)


@given(simple_shaped_rules(), pressed_released_or(), st.data())
def test_pressed_released_or_trigger_is_never_simple(rule, pair, data):
    """Swap a simple rule's trigger for the pressed/released Or, or add the Or next to it."""
    components = list(rule.components)
    (trigger,) = [i for i, c in enumerate(components) if isinstance(c, (Key, MouseGesture))]
    if data.draw(st.booleans()):
        components[trigger] = pair
    else:
        components.insert(trigger + data.draw(st.integers(0, 1)), pair)
    assert recognize(Rule(components)) is None
    assert not_simple_reason(Rule(components)) == "Or condition"


@settings(max_examples=500)
@given(near_simple_rules() | _components(canonical=False).filter(lambda c: isinstance(c, Rule)))
def test_recognized_rules_regenerate_byte_identically(rule):
    simple = recognize(rule)
    if simple is not None:
        assert _text(generate(simple)) == _text(rule)


def new_simple_rules(names=names):
    """SimpleRules built in code. `names` gives control names (for triggers and gesture items)."""
    return st.builds(
        SimpleRule,
        trigger=st.builds(KeyTrigger, names, st.sampled_from(TRIGGER_KEY_ACTIONS))
        | st.builds(GestureTrigger, st.lists(st.sampled_from(MOVEMENTS) | names, min_size=1, max_size=3)),
        actions=st.lists(_leaves(canonical=True, actions_only=True), min_size=1, max_size=3),
        device=st.none() | device_ids,
        modifiers=st.none() | st.lists(st.sampled_from(MODIFIER_NAMES), max_size=3),
        process=st.none() | st.text(max_size=8),
    )


@settings(max_examples=300)
@given(new_simple_rules())
def test_new_simple_rules_round_trip(simple):
    rule = generate(simple)
    assert recognize(rule) == simple
    # Reloaded from its text it is the same simple rule (actions compare by text: a loaded component
    # records its argument shape, a new one does not) and regenerates the same text.
    (reloaded,) = loads(_text(rule)).rules
    again = recognize(reloaded)
    assert replace(again, actions=simple.actions) == simple
    assert _text(Rule(again.actions)) == _text(Rule(simple.actions))
    assert _text(generate(again)) == _text(rule)
