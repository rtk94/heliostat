# SPDX-License-Identifier: GPL-2.0-or-later
"""rules.yaml loading (strict) and Solaar-style serialization."""

import textwrap
from pathlib import Path

import pytest
import yaml

from heliostat.model import Active, Device, Feature, Host, Key, Process, Raw, Rule, RuleSet, Set, Setting
from heliostat.rulesfile import RulesParseError, dumps, load, loads
from tests.conformance.deviations import d2_shape_differences

FIXTURES = Path(__file__).parent / "fixtures" / "rules"


def _parses(path):
    try:
        load(path)
    except RulesParseError:
        return False
    return True


PARSEABLE = [f for f in sorted(FIXTURES.glob("*.yaml")) if _parses(f)]


def _text(s):
    return textwrap.dedent(s).lstrip("\n")


def _one(component_text):
    return loads(f"---\n- {component_text}\n...\n").rules[0].components[0]


def _dumped(component_text):
    """dumps() of a one-component rule, without the header and document markers."""
    out = dumps(loads(f"---\n- {component_text}\n...\n"))
    assert out.startswith("%YAML 1.3\n---\n") and out.endswith("...\n")
    return out[len("%YAML 1.3\n---\n") : -len("...\n")]


# (as written, as dumps() writes it). Formatting follows Solaar's save: scalar-only lists in flow
# style, other lists in block style. Unlike Solaar's save, a one-item list is never collapsed (D2).
DUMPS = [
    ("Key: Back Button", "- Key: Back Button\n"),
    ("Key: [Back Button]", "- Key: [Back Button]\n"),
    ("Key: [Back Button, released]", "- Key: [Back Button, released]\n"),
    ("Modifiers: [Alt]", "- Modifiers: [Alt]\n"),
    ("Test: [crown_pressed]", "- Test: [crown_pressed]\n"),
    ("Test: [crown_tap, null]", "- Test:\n  - crown_tap\n  - null\n"),
    ("KeyPress: XF86_AudioMute", "- KeyPress: XF86_AudioMute\n"),
    ("KeyPress: [Super_L, depress]", "- KeyPress:\n  - Super_L\n  - depress\n"),
    ("KeyPress: [[Super_L], depress]", "- KeyPress:\n  - [Super_L]\n  - depress\n"),
    ("KeyPress: [[Control_L, Tab], click]", "- KeyPress:\n  - [Control_L, Tab]\n  - click\n"),
    ("MouseScroll: [[0, 1]]", "- MouseScroll:\n  - [0, 1]\n"),
    (
        "Setting: [null, divert-keys, Smart Shift, Diverted]",
        "- Setting:\n  - null\n  - divert-keys\n  - Smart Shift\n  - Diverted\n",
    ),
    ("Not: {Modifiers: [Alt]}", "- Not:\n    Modifiers: [Alt]\n"),
    ("Not: [Process: kwin]", "- Not:\n  - Process: kwin\n"),
    ("Rule: [ Test: crown_tap, KeyPress: a ]", "- Rule:\n  - Test: crown_tap\n  - KeyPress: a\n"),
    ("Rule: []", "- Rule: []\n"),
    ("Later: [2]", "- Later: [2]\n"),
    ("Later: [0.5, Execute: [notify-send, done]]", "- Later:\n  - 0.5\n  - Execute: [notify-send, done]\n"),
    ("Execute: [xflock4]", "- Execute: [xflock4]\n"),
    # Raw: Solaar does not load [x] and x alike for these, so its own save's collapse changes them.
    ("MouseScroll: [1]", "- MouseScroll: [1]\n"),
    ("KeyIsDown: [Back Button]", "- KeyIsDown: [Back Button]\n"),
    ("Device: [MX Master 3]", "- Device: [MX Master 3]\n"),
    ("TestBytes: [1]", "- TestBytes: [1]\n"),
    ("Set: [null, dpi, [1600]]", "- Set:\n  - null\n  - dpi\n  - [1600]\n"),
    ("Rule: [5]", "- Rule: [5]\n"),
]


@pytest.mark.parametrize(("source", "expected"), DUMPS, ids=[s for s, _ in DUMPS])
def test_dumps_component(source, expected):
    assert _dumped(source) == expected


def test_dumps_header_and_document_markers():
    ruleset = RuleSet([Rule([Key("Back Button")]), Rule([Process("firefox")])])
    assert dumps(ruleset) == _text("""
        %YAML 1.3
        ---
        - Key: [Back Button, pressed]
        ...
        ---
        - Process: firefox
        ...
        """)


def test_dumps_empty_ruleset_is_empty():
    # Solaar writes the %YAML line only when there are rules, and dump_all([]) writes nothing.
    assert dumps(RuleSet()) == ""
    assert loads("").rules == []


def test_dumps_empty_rule():
    assert dumps(RuleSet([Rule([])])) == "%YAML 1.3\n--- []\n...\n"


def test_scalar_types_preserved():
    text = _text("""
        ---
        - Device: 12345678
        - Active: '12345678'
        - Host: '1.5'
        - Process: 'true'
        - Set: [12345678, dpi, 1600.0]
        - Setting: [MX Master 3, hires-smooth-invert, false]
        ...
        """)
    rule = loads(text).rules[0]
    assert rule.components == [
        Device(12345678),
        Active("12345678"),
        Host("1.5"),
        Process("true"),
        Set(12345678, "dpi", [1600.0]),
        Setting("MX Master 3", "hires-smooth-invert", [False]),
    ]
    assert type(rule.components[0].device) is int
    assert type(rule.components[4].values[0]) is float
    assert type(rule.components[5].values[0]) is bool
    assert dumps(loads(text)) == "%YAML 1.3\n" + text


def test_feature_arguments_preserved_in_all_forms():
    text = _text("""
        %YAML 1.3
        ---
        - Feature: THUMB_WHEEL
        ...
        ---
        - Feature: THUMB WHEEL
        ...
        ---
        - Feature: None
        ...
        """)
    ruleset = loads(text)
    assert [r.components[0] for r in ruleset.rules] == [Feature("THUMB_WHEEL"), Feature("THUMB WHEEL"), Feature("None")]
    assert dumps(ruleset) == text


def test_raw_passthrough_unknown_component():
    text = _text("""
        %YAML 1.3
        ---
        - Key: [Back Button, pressed]
        - Frobnicate:
            speed: 3
            targets: [a, b]
        - Rule:
          - NotYetInvented: [1]
          - KeyPress:
            - a
            - click
        ...
        ---
        Key: Back Button
        ...
        """)
    ruleset = loads(text)
    assert ruleset.rules[0].components[1] == Raw({"Frobnicate": {"speed": 3, "targets": ["a", "b"]}})
    assert isinstance(ruleset.rules[1], Raw)
    assert dumps(ruleset) == text


@pytest.mark.parametrize("fixture", PARSEABLE, ids=[f.stem for f in PARSEABLE])
def test_fixture_dumps_is_idempotent_and_keeps_shapes(fixture):
    """As-written fixtures (docs/decisions.md, "Formatting tests restructured" and D2)."""
    once = dumps(load(fixture))
    assert dumps(loads(once)) == once
    # Idempotence alone would not catch dumps rewriting shapes the way Solaar's save does (that
    # rewrite is idempotent too), so also check D2: the output loads with the original's structure.
    dumped, original = list(yaml.safe_load_all(once)), list(yaml.safe_load_all(fixture.read_bytes()))
    assert d2_shape_differences(dumped, original) is None, d2_shape_differences(dumped, original)


def test_harmless_one_item_lists_are_kept():
    # Solaar's save would collapse each of these, and Solaar reads [x] and x alike for all of them;
    # D2 keeps them as written anyway.
    assert _text("""
        ---
        - Key: [Smart Shift]
        - Modifiers: [Super]
        - MouseGesture: [Mouse Down]
        - Later:
          - 5
          - KeyPress: [XF86_AudioMute]
        - Execute: [xflock4]
        ...
        """) in dumps(load(FIXTURES / "argument-forms.yaml"))


def test_broken_docs_example_raises_with_position_and_count():
    with pytest.raises(RulesParseError) as info:
        load(FIXTURES / "solaar-docs-example.yaml")
    error = info.value
    # Line 18 is `- Feature: CROWN`, right after the third rule's `...` with no `---` before it.
    assert (error.line, error.column) == (18, 1)
    assert error.documents_parsed == 3
    assert error.path == FIXTURES / "solaar-docs-example.yaml"
    assert "line 18, column 1" in str(error)
    assert "3 rule(s) parsed" in str(error)


def test_parse_error_in_first_document():
    with pytest.raises(RulesParseError) as info:
        loads("---\n- Key: [Back Button\n...\n")
    assert info.value.documents_parsed == 0
    assert info.value.line is not None


def test_parse_error_after_valid_documents_is_not_partial():
    text = "---\n- Key: a\n...\n---\n- Key: b\n...\n---\n- Key: {c\n"
    with pytest.raises(RulesParseError) as info:
        loads(text)
    assert info.value.documents_parsed == 2


def test_invalid_utf8_is_a_parse_error():
    with pytest.raises(RulesParseError) as info:
        loads(b"---\n- Process: \xff\n...\n")
    assert info.value.documents_parsed == 0
