# SPDX-License-Identifier: GPL-2.0-or-later
"""Property tests: random valid rule trees, dumped by Heliostat, loaded by real Solaar.

Each example costs a few Solaar subprocesses, so example counts are kept small.
"""

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from heliostat.model import (
    CLICK,
    CLICK_ACTIONS,
    KEY_ACTIONS,
    NO_PARAMETER,
    PRESSED,
    Active,
    And,
    Device,
    Execute,
    Feature,
    Host,
    Key,
    KeyIsDown,
    KeyPress,
    KeyPressForm,
    Later,
    Modifiers,
    MouseClick,
    MouseGesture,
    MouseProcess,
    MouseScroll,
    Not,
    Or,
    Process,
    Report,
    Rule,
    RuleSet,
    Set,
    Setting,
    Test,
    TestBytes,
)
from heliostat.rulesfile import dumps
from tests.conformance.deviations import formatting_differences
from tests.conformance.harness import SOLAAR_TAGS, solaar_dump_data, solaar_roundtrip
from tests.conformance.strict import assert_same_data

# Vocabulary that both pinned Solaar versions accept, so data() gives back what was written. Checked
# against .solaar/<tag>/lib/logitech_receiver: special_keys.CONTROL (str(CONTROL[name]) == name),
# hidpp20_constants.SupportedFeature, diversion.TESTS, diversion.MODIFIERS and diversion.buttons
# (with evdev installed, as on the dev machine).
CONTROLS = [
    "Back Button",
    "Forward Button",
    "Smart Shift",
    "Mouse Gesture Button",
    "M2",
    "Host Switch Channel 2",
    "Brightness Up",
    "Left Button",
    "Middle Button",
    "Virtual Gesture Button",
    "G1",
    "MR",
    "Volume Up",
    "Mute",
]
FEATURES = ["CROWN", "THUMB_WHEEL", "LOWRES_WHEEL", "HIRES_WHEEL", "REPROG_CONTROLS_V4", "MOUSE_GESTURE", "GKEY"]
TESTS = [
    "crown_right",
    "crown_left",
    "crown_right_ratchet",
    "crown_left_ratchet",
    "crown_tap",
    "crown_start_press",
    "crown_end_press",
    "crown_pressed",
    "thumb_wheel_up",
    "thumb_wheel_down",
    "lowres_wheel_up",
    "lowres_wheel_down",
    "hires_wheel_up",
    "hires_wheel_down",
    "charging",
    "False",
    "True",
]
MODIFIER_NAMES = ["Shift", "Control", "Alt", "Super"]
BUTTONS = ["left", "middle", "right", "scroll_up", "scroll_down", "scroll_left", "scroll_right", "button8", "button9"]
MOVEMENTS = ["Mouse Up", "Mouse Down", "Mouse Left", "Mouse Right", "Mouse Up-left", "Mouse Down-right"]

text = st.text(max_size=8)
ints = st.integers(min_value=-(2**40), max_value=2**40)
floats = st.floats(allow_nan=False, width=64)
numbers = ints | floats
scalars = text | ints | floats | st.booleans()
device_ids = text | ints


def _leaves(canonical: bool, actions_only: bool = False):
    """Leaf components. canonical=True leaves form fields at their defaults (Solaar's saved shape).

    actions_only=True gives only the action leaves (KeyPress, MouseScroll, MouseClick, Set, Execute).
    """
    flag = st.just(True) if canonical else st.booleans()
    # Form fields whose default (None, built in code) collapses a one-item list as Solaar's save does.
    form_flag = st.none() if canonical else st.sampled_from([True, False, None])

    key_action = st.sampled_from(KEY_ACTIONS if canonical else [None, *KEY_ACTIONS])

    keypress_form = st.none() if canonical else st.sampled_from([None, *KeyPressForm])

    @st.composite
    def keypress(draw):
        form = draw(keypress_form)
        n = 1 if form in (KeyPressForm.SCALAR, KeyPressForm.PAIR) else draw(st.integers(1, 3))
        keys = draw(st.lists(text, min_size=n, max_size=n))
        if form in (KeyPressForm.SCALAR, KeyPressForm.LIST):
            return KeyPress(keys, None, form)
        actions = st.sampled_from(CLICK_ACTIONS)
        if form is None and not canonical:
            actions = st.none() | actions
        return KeyPress(keys, draw(actions), form)

    @st.composite
    def mouse_click(draw):
        count = draw(st.just(1) | ints | st.sampled_from(CLICK_ACTIONS))
        if not canonical:
            count = draw(st.none() | st.just(count))
        return MouseClick(draw(st.sampled_from(BUTTONS)), count, draw(flag))

    @st.composite
    def test(draw):
        name = draw(st.sampled_from(TESTS))
        if draw(st.booleans()):
            # Solaar's data() drops a None parameter, so None is not a canonical shape.
            return Test(name, draw(scalars if canonical else st.none() | scalars), draw(form_flag))
        return Test(name, NO_PARAMETER, draw(form_flag))

    @st.composite
    def test_bytes(draw):
        start = draw(st.integers(0, 15))
        end = draw(st.integers(start + 1, 16))
        return TestBytes([start, end, *draw(st.lists(ints, min_size=1, max_size=2))])

    def single_or_list(cls, elements):
        # listed=False only round-trips as a scalar when there is exactly one element.
        if canonical:
            return st.lists(elements, max_size=3).map(cls)
        listed = st.builds(cls, st.lists(elements, max_size=3), st.sampled_from([True, None]))
        return listed | elements.map(lambda x: cls([x], False))

    conditions = [
        st.builds(Process, text),
        st.builds(MouseProcess, text),
        st.sampled_from(FEATURES).map(Feature.new),
        st.builds(Report, ints),
        st.builds(Setting, st.none() | device_ids, text, st.lists(st.none() | scalars, min_size=1, max_size=2)),
        single_or_list(Modifiers, st.sampled_from(MODIFIER_NAMES)),
        st.builds(Key, st.sampled_from(CONTROLS), key_action, flag),
        st.builds(KeyIsDown, st.sampled_from(CONTROLS)),
        test(),
        test_bytes(),
        single_or_list(MouseGesture, st.sampled_from(MOVEMENTS + CONTROLS) | text),
        st.builds(Active, device_ids),
        st.builds(Device, device_ids),
        st.builds(Host, device_ids),
    ]
    actions = [
        keypress(),
        st.builds(MouseScroll, numbers, numbers, st.just(False) if canonical else st.booleans()),
        mouse_click(),
        st.builds(Set, st.none() | device_ids, text, st.lists(st.none() | scalars, min_size=1, max_size=2)),
        single_or_list(Execute, text),
    ]
    return st.one_of(actions if actions_only else conditions + actions)


def _components(canonical: bool):
    not_listed = st.just(False) if canonical else st.booleans()
    delays = st.integers(1, 100) | st.floats(0.01, 100)

    def extend(children):
        child_lists = st.lists(children, max_size=3)
        return st.one_of(
            child_lists.map(Rule),
            child_lists.map(Or),
            child_lists.map(And),
            st.builds(Not, children, not_listed),
            st.builds(Later, delays, child_lists, st.none() if canonical else st.sampled_from([True, False, None])),
        )

    return st.recursive(_leaves(canonical), extend, max_leaves=8)


def rulesets(canonical: bool):
    rule = st.lists(_components(canonical), min_size=1, max_size=4).map(Rule)
    return st.lists(rule, min_size=1, max_size=3).map(RuleSet)


def expected_data(component):
    """What Solaar's data() returns after loading this component, for the vocabulary above."""
    match component:
        case Rule() | Or() | And():
            return {component.TYPE: [expected_data(c) for c in component.components]}
        case Not():
            return {"Not": expected_data(component.component)}
        case Process() | MouseProcess():
            return {component.TYPE: component.process}
        case Feature():
            return {"Feature": component.feature.replace("_", " ")}  # str(SupportedFeature)
        case Report():
            return {"Report": component.report}
        case Setting() | Set():
            return {component.TYPE: [component.device, component.setting, *component.values]}
        case Modifiers():
            return {"Modifiers": list(component.modifiers)}
        case Key():
            return {"Key": [component.key, component.action or PRESSED]}
        case KeyIsDown():
            return {"KeyIsDown": component.key}
        case Test():
            parameter = component.parameter if component.has_parameter else None
            return {"Test": [component.test] + ([parameter] if parameter is not None else [])}
        case TestBytes():
            return {"TestBytes": list(component.values)}
        case MouseGesture():
            return {"MouseGesture": list(component.movements)}
        case Active() | Device():
            return {component.TYPE: component.device}
        case Host():
            return {"Host": component.host}
        case KeyPress():
            return {"KeyPress": [list(component.keys), component.action or CLICK]}
        case MouseScroll():
            return {"MouseScroll": [component.dx, component.dy]}
        case MouseClick():
            return {"MouseClick": [component.button, 1 if component.count is None else component.count]}
        case Execute():
            return {"Execute": list(component.args)}
        case Later():
            return {"Later": [component.delay, *(expected_data(c) for c in component.components)]}
    raise AssertionError(f"no expected data for {component!r}")


def _json_normalized(data):
    # dump-data goes through json; floats like inf become Infinity and come back as float('inf').
    return json.loads(json.dumps(data))


PROPERTY_SETTINGS = settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)


@pytest.mark.conformance
@PROPERTY_SETTINGS
@given(rulesets(canonical=False))
def test_solaar_loads_random_rules_as_heliostat_holds_them(ruleset):
    expected = _json_normalized([expected_data(r) for r in ruleset.rules])
    with tempfile.TemporaryDirectory(prefix="heliostat-property-") as tmp:
        path = Path(tmp) / "rules.yaml"
        path.write_text(dumps(ruleset))
        for tag in SOLAAR_TAGS:
            assert_same_data(solaar_dump_data(tag, path), expected)


@pytest.mark.conformance
@settings(PROPERTY_SETTINGS, max_examples=25)
@given(rulesets(canonical=True))
def test_solaar_save_of_new_rules_matches_dumps(ruleset):
    """Rules built in code (the shapes Solaar's data() writes) format exactly as Solaar saves them."""
    heliostat = dumps(ruleset)
    with tempfile.TemporaryDirectory(prefix="heliostat-property-") as tmp:
        path = Path(tmp) / "rules.yaml"
        path.write_text(heliostat)
        for tag in SOLAAR_TAGS:
            solaar = solaar_roundtrip(tag, path, Path(tmp) / f"solaar-{tag}.yaml").decode()
            diff = formatting_differences(heliostat, solaar, tag)
            assert diff is None, f"differs from Solaar {tag}'s save beyond the documented deviations:\n{diff}"
