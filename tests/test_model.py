# SPDX-License-Identifier: GPL-2.0-or-later
"""Rule components: parse from and serialize to PyYAML structures."""

import copy

import pytest
import yaml

from heliostat.model import (
    COMPONENT_TYPES,
    NO_PARAMETER,
    Active,
    And,
    Device,
    Execute,
    Feature,
    FeatureArgForm,
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
    Raw,
    Report,
    Rule,
    RuleSet,
    Set,
    Setting,
    Test,
    TestBytes,
    component_from_yaml,
    feature_argument_form,
)
from tests.conformance.strict import assert_same_data

# (component as written in rules.yaml, the model it parses to)
CASES = [
    (
        "Rule: [Key: Back Button, KeyPress: a]",
        Rule([Key("Back Button", None, False), KeyPress(["a"], None, KeyPressForm.SCALAR)]),
    ),
    ("Rule: []", Rule([])),
    ("Not: {Process: kwin}", Not(Process("kwin"))),
    ("Not: [Process: kwin]", Not(Process("kwin"), listed=True)),
    (
        "Or: [Test: crown_tap, Test: crown_pressed]",
        Or([Test("crown_tap", listed=False), Test("crown_pressed", listed=False)]),
    ),
    ("And: [Modifiers: Shift]", And([Modifiers(["Shift"], listed=False)])),
    ("Process: firefox", Process("firefox")),
    ("MouseProcess: konsole", MouseProcess("konsole")),
    ("Feature: CROWN", Feature("CROWN")),
    ("Feature: THUMB_WHEEL", Feature("THUMB_WHEEL")),
    ("Feature: THUMB WHEEL", Feature("THUMB WHEEL")),
    ("Feature: None", Feature("None")),
    ("Report: 0", Report(0)),
    ("Setting: [null, divert-keys, Smart Shift, Diverted]", Setting(None, "divert-keys", ["Smart Shift", "Diverted"])),
    ("Setting: [MX Master 3, hires-smooth-invert, true]", Setting("MX Master 3", "hires-smooth-invert", [True])),
    ("Modifiers: Control", Modifiers(["Control"], listed=False)),
    ("Modifiers: [Alt]", Modifiers(["Alt"], listed=True)),
    ("Modifiers: [Shift, Control]", Modifiers(["Shift", "Control"], listed=True)),
    ("Modifiers: []", Modifiers([], listed=True)),
    ("Key: Back Button", Key("Back Button", None, listed=False)),
    ("Key: [Back Button]", Key("Back Button", None)),
    ("Key: [Back Button, released]", Key("Back Button", "released")),
    ("KeyIsDown: Back Button", KeyIsDown("Back Button")),
    ("Test: crown_tap", Test("crown_tap", listed=False)),
    ("Test: [crown_tap]", Test("crown_tap", listed=True)),
    ("Test: [thumb_wheel_up, 10]", Test("thumb_wheel_up", 10, listed=True)),
    ("Test: [crown_tap, null]", Test("crown_tap", None, listed=True)),
    ("TestBytes: [0, 1, 128]", TestBytes([0, 1, 128])),
    ("TestBytes: [2, 4, -10, 10]", TestBytes([2, 4, -10, 10])),
    ("MouseGesture: Mouse Down", MouseGesture(["Mouse Down"], listed=False)),
    ("MouseGesture: [Mouse Gesture Button, Mouse Up]", MouseGesture(["Mouse Gesture Button", "Mouse Up"], listed=True)),
    ("Active: 198E3EB8", Active("198E3EB8")),
    ("Device: 12345678", Device(12345678)),
    ("Device: '12345678'", Device("12345678")),
    ("Host: workstation", Host("workstation")),
    ("KeyPress: XF86_AudioMute", KeyPress(["XF86_AudioMute"], None, KeyPressForm.SCALAR)),
    ("KeyPress: [Control_L, t]", KeyPress(["Control_L", "t"], None, KeyPressForm.LIST)),
    ("KeyPress: [Super_L, depress]", KeyPress(["Super_L"], "depress", KeyPressForm.PAIR)),
    ("KeyPress: [[Control_L, Tab], click]", KeyPress(["Control_L", "Tab"], "click", KeyPressForm.NESTED)),
    ("MouseScroll: [0, 1]", MouseScroll(0, 1)),
    ("MouseScroll: [-1.5, 0]", MouseScroll(-1.5, 0)),
    ("MouseScroll: [[0, 1]]", MouseScroll(0, 1, nested=True)),
    ("MouseClick: middle", MouseClick("middle", None, listed=False)),
    ("MouseClick: [left]", MouseClick("left", None)),
    ("MouseClick: [left, 2]", MouseClick("left", 2)),
    ("MouseClick: [right, click]", MouseClick("right", "click")),
    ("Set: [12345678, dpi, 1600]", Set(12345678, "dpi", [1600])),
    ("Set: [null, smart-shift, 20]", Set(None, "smart-shift", [20])),
    ("Execute: xflock4", Execute(["xflock4"], listed=False)),
    ("Execute: [notify-send, done]", Execute(["notify-send", "done"], listed=True)),
    ("Later: 2", Later(2, [], listed=False)),
    ("Later: [2]", Later(2, [], listed=True)),
    (
        "Later: [0.5, Execute: [notify-send, done]]",
        Later(0.5, [Execute(["notify-send", "done"], listed=True)], listed=True),
    ),
]


def _load(text):
    return yaml.safe_load(text)


def test_cases_cover_every_component_type():
    covered = {type(model).TYPE for _, model in CASES}
    assert covered == set(COMPONENT_TYPES)
    assert len(COMPONENT_TYPES) == 24


@pytest.mark.parametrize(("source", "model"), CASES, ids=[s for s, _ in CASES])
def test_component_parses(source, model):
    assert component_from_yaml(_load(source)) == model


@pytest.mark.parametrize(("source", "model"), CASES, ids=[s for s, _ in CASES])
def test_component_serializes_as_loaded(source, model):
    loaded = _load(source)
    assert_same_data(component_from_yaml(loaded).to_yaml(), loaded)
    assert_same_data(model.to_yaml(), loaded)


@pytest.mark.parametrize(("source", "model"), CASES, ids=[s for s, _ in CASES])
def test_component_from_yaml_on_its_class(source, model):
    assert type(model).from_yaml(_load(source)) == model


def test_constructor_defaults_are_solaar_saved_shapes():
    # What Solaar's save writes for each (data(), then one-item scalar lists collapsed), so new
    # components save the way Solaar's editor would. Built in code is the only place lists collapse.
    assert Key("Back Button").to_yaml() == {"Key": ["Back Button", "pressed"]}
    assert KeyPress(["Control_L", "t"]).to_yaml() == {"KeyPress": [["Control_L", "t"], "click"]}
    assert KeyPress(["XF86_AudioMute"]).to_yaml() == {"KeyPress": ["XF86_AudioMute", "click"]}
    assert MouseClick("left").to_yaml() == {"MouseClick": ["left", 1]}
    assert Modifiers(["Shift"]).to_yaml() == {"Modifiers": "Shift"}
    assert Modifiers(["Shift", "Alt"]).to_yaml() == {"Modifiers": ["Shift", "Alt"]}
    assert Test("crown_tap").to_yaml() == {"Test": "crown_tap"}
    assert Test("thumb_wheel_up", 10).to_yaml() == {"Test": ["thumb_wheel_up", 10]}
    assert Not(Process("kwin")).to_yaml() == {"Not": {"Process": "kwin"}}
    assert MouseGesture(["Mouse Up"]).to_yaml() == {"MouseGesture": "Mouse Up"}
    assert Execute(["xflock4"]).to_yaml() == {"Execute": "xflock4"}
    assert Later(2).to_yaml() == {"Later": 2}
    assert Later(2, [Execute(["x"])]).to_yaml() == {"Later": [2, {"Execute": "x"}]}
    assert MouseScroll(0, 1).to_yaml() == {"MouseScroll": [0, 1]}


def test_edited_component_drops_a_shorthand_form_it_no_longer_fits():
    key = component_from_yaml({"Key": "Back Button"})
    key.action = "released"
    assert key.to_yaml() == {"Key": ["Back Button", "released"]}

    keypress = component_from_yaml({"KeyPress": "a"})
    keypress.keys.append("b")
    assert keypress.to_yaml() == {"KeyPress": ["a", "b"]}

    modifiers = component_from_yaml({"Modifiers": "Shift"})
    modifiers.modifiers.append("Alt")
    assert modifiers.to_yaml() == {"Modifiers": ["Shift", "Alt"]}


def test_keypress_never_writes_keys_that_would_load_as_an_action():
    # [a, click] loads as key a with action click, so keys [a, click] without an action are nested.
    assert KeyPress(["a", "click"], None, KeyPressForm.LIST).to_yaml() == {"KeyPress": [["a", "click"], "click"]}


@pytest.mark.parametrize(
    "source",
    [
        "Key: [Back Button]",
        "Modifiers: [Alt]",
        "Test: [crown_tap]",
        "MouseGesture: [Mouse Up]",
        "Execute: [xflock4]",
        "Later: [2]",
        "MouseClick: [left]",
        "KeyPress: [[Super_L], depress]",
        "KeyPress: [XF86_AudioMute]",
    ],
)
def test_loaded_one_item_list_is_never_collapsed(source):
    # D2: kept even where Solaar's save would collapse it harmlessly.
    loaded = _load(source)
    assert_same_data(component_from_yaml(loaded).to_yaml(), loaded)


def test_test_without_parameter_survives_deepcopy():
    test = copy.deepcopy(Test("crown_tap"))
    assert test.parameter is NO_PARAMETER
    assert not test.has_parameter


@pytest.mark.parametrize(
    "source",
    [
        "Frobnicate: 3",
        "{Key: Back Button, KeyPress: a}",
        "just a string",
        "[Key, Back Button]",
        "Key: [Back Button, pressed, extra]",
        "Key: [Back Button, down]",
        "Key: 5",
        "KeyIsDown: [Back Button]",
        "Not: [Key: a, Key: b]",
        "Not: []",
        "Or: {Key: Back Button}",
        "Rule: 5",
        "Process: 42",
        "Process: [firefox]",
        "Feature: [CROWN]",
        "Feature: null",
        "Report: x",
        "Report: true",
        "Setting: [dev, dpi]",
        "Set: [null, dpi, [1600]]",
        "Modifiers: [Shift, 5]",
        "Test: [5]",
        "Test: [crown_tap, 1, 2]",
        "TestBytes: [1]",
        "TestBytes: [0, 1]",
        "MouseGesture: [5]",
        "Device: [MX Master 3]",
        "Device: null",
        "KeyPress: [[Control_L]]",
        "KeyPress: 5",
        "MouseScroll: [1]",
        "MouseScroll: 5",
        "MouseClick: 5",
        "MouseClick: [5]",
        "MouseClick: [left, '2']",
        "Execute: [5]",
        "Later: []",
        "Later: [soon]",
    ],
)
def test_unknown_or_malformed_component_is_raw_and_kept_verbatim(source):
    loaded = _load(source)
    component = component_from_yaml(loaded)
    assert isinstance(component, Raw)
    assert component.reason
    assert_same_data(component.to_yaml(), loaded)


def test_raw_inside_typed_containers():
    rule = component_from_yaml(_load("Rule: [Frobnicate: 3, Key: Back Button]"))
    assert rule == Rule([Raw({"Frobnicate": 3}), Key("Back Button", None, listed=False)])
    later = component_from_yaml(_load("Later: [500, Frobnicate: 3]"))
    assert later == Later(500, [Raw({"Frobnicate": 3})], listed=True)
    assert component_from_yaml(_load("Not: {Frobnicate: 3}")) == Not(Raw({"Frobnicate": 3}))


def test_raw_copies_loaded_data():
    shared = ["Back Button"]
    raw = component_from_yaml({"KeyIsDown": shared})
    shared.append("changed")
    assert raw.to_yaml() == {"KeyIsDown": ["Back Button"]}


def test_raw_type_name():
    assert Raw({"Frobnicate": 3}).type_name == "Frobnicate"
    assert Raw("text").type_name is None


@pytest.mark.parametrize(
    ("argument", "form"),
    [
        ("CROWN", FeatureArgForm.NAME),
        ("THUMB_WHEEL", FeatureArgForm.NAME),
        ("THUMB WHEEL", FeatureArgForm.SPACED),
        ("None", FeatureArgForm.NONE),
    ],
)
def test_feature_argument_form(argument, form):
    assert feature_argument_form(argument) == form
    assert Feature(argument).argument_form == form


def test_new_feature_uses_underscores():
    assert Feature.new("THUMB WHEEL") == Feature("THUMB_WHEEL")
    assert Feature.new("CROWN").to_yaml() == {"Feature": "CROWN"}


def test_ruleset_keeps_non_list_documents_as_raw():
    documents = [[{"Key": "Back Button"}], {"Key": "Back Button"}, None]
    ruleset = RuleSet.from_yaml(documents)
    assert ruleset.rules[0] == Rule([Key("Back Button", None, listed=False)])
    assert ruleset.rules[1] == Raw({"Key": "Back Button"})
    assert ruleset.rules[2] == Raw(None)
    assert_same_data(ruleset.to_yaml(), documents)
