# SPDX-License-Identifier: GPL-2.0-or-later
"""Lint checks HL000-HL010 against FakeSolaar device data, with cases that must and must not trigger each.

Lint's claims about Solaar itself (which documents abort its load, what its save damages, where its
processing stops) are checked against real Solaar in tests/conformance/test_lint_claims.py.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from heliostat.analysis import (
    CODES,
    LintContext,
    Session,
    Severity,
    component_at,
    lint_file,
    lint_text,
    locations,
    model_path,
)
from heliostat.model import Feature, Key, MouseGesture
from heliostat.rulesfile import loads
from heliostat.solaar import Control, DivertMode, FakeSolaar, SolaarCommandError

FIXTURES = Path(__file__).parent / "fixtures"
RULES = FIXTURES / "rules"
SHOW_GESTURES_1114 = FIXTURES / "solaar" / "1.1.14" / "show_all_back-gestures.txt"
SHOW_1120 = FIXTURES / "solaar" / "1.1.20" / "show_all.txt"
X11 = {"XDG_SESSION_TYPE": "x11", "XDG_CURRENT_DESKTOP": "KDE"}
WAYLAND_KDE = {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"}


def _context(show=SHOW_GESTURES_1114, version=(1, 1, 14), env=X11):
    return LintContext.from_client(FakeSolaar.from_show(show.read_text(), version=version), env=env)


CTX = _context()  # Solaar 1.1.14; Signature M650 with Back Button in Mouse Gestures, all else Regular
CTX_1120 = _context(SHOW_1120, (1, 1, 20))  # Solaar 1.1.20; every control Regular
NO_DEVICES = LintContext(version=(1, 1, 14))


def _rules(*documents: str) -> str:
    return "%YAML 1.3\n" + "".join(f"---\n{d}\n...\n" for d in documents)


def _lint(*documents, ctx=CTX):
    return [p for p in lint_text(_rules(*documents), ctx) if p.severity is not Severity.NOTE]


def _found(problems, code):
    return [p for p in problems if p.code == code]


def _paths(problems, code):
    return [p.rule_path for p in _found(problems, code)]


def test_every_code_has_a_name():
    assert sorted(CODES) == [f"HL{n:03}" for n in range(11)]
    assert len(set(CODES.values())) == len(CODES)


# Fixtures as a whole


@pytest.mark.parametrize("fixture", sorted(RULES.glob("*.yaml")), ids=lambda p: p.stem)
@pytest.mark.parametrize("ctx", [CTX, CTX_1120, NO_DEVICES, LintContext(), _context(env=WAYLAND_KDE)])
def test_lint_runs_on_every_fixture(fixture, ctx):
    for p in lint_file(fixture, ctx):
        assert p.code in CODES or (p.code == "" and p.severity is Severity.NOTE)
        assert p.message


def test_lint_cases_fixture():
    problems = lint_file(RULES / "lint-cases.yaml", _context(env=WAYLAND_KDE))
    found = sorted((p.rule_path, p.code) for p in problems if p.severity is not Severity.NOTE)
    assert found == [
        ((0, 0), "HL001"),
        ((2, 0), "HL001"),
        ((3, 0), "HL002"),
        ((3, 0), "HL010"),
        ((4, 0), "HL002"),
        ((5,), "HL003"),
        ((5, 0), "HL001"),
        ((6,), "HL004"),
        ((7, 1), "HL005"),
        ((8, 1), "HL006"),
    ]


@pytest.mark.parametrize("ctx", [CTX, replace(CTX, version=(1, 1, 20))])
def test_lint_clean_fixture_reports_nothing(ctx):
    assert lint_file(RULES / "lint-clean.yaml", ctx) == []


# HL000


def test_parse_error_reports_position_and_rules_running():
    (p,) = lint_file(RULES / "solaar-docs-example.yaml", CTX)
    assert (p.code, p.severity, p.rule_path) == ("HL000", Severity.ERROR, ())
    assert "line 18, column 1" in p.message
    assert "only the 3 rules before the error" in p.message
    assert "drops everything after it" in p.message


def test_parse_error_runs_no_other_checks():
    problems = lint_text(_rules("- Key: Not A Real Key\n- Feature: None") + "- [unclosed\n", CTX)
    assert [p.code for p in problems] == ["HL000"]
    assert "only the 1 rule before" in problems[0].message


# HL001


def test_undiverted_key():
    (p,) = _found(_lint("- Key: [Forward Button, pressed]\n- KeyPress: a"), "HL001")
    assert p.severity is Severity.ERROR and p.rule_path == (0, 0)
    assert "Forward Button is not diverted (Signature M650 Mouse: Regular)" in p.message
    assert p.fix.command == ("solaar", "config", "AAAA0002", "divert-keys", "Forward Button", "Diverted")


@pytest.mark.parametrize(
    "rule",
    [
        "- KeyIsDown: Forward Button\n- KeyPress: a",
        "- Or: [Key: Middle Button, Key: Back Button]\n- KeyPress: a",
        "- Rule: [Key: Forward_Button, KeyPress: a]",
    ],
)
def test_undiverted_key_anywhere_in_the_rule(rule):
    assert len(_found(_lint(rule), "HL001")) == 1


@pytest.mark.parametrize(
    "rule",
    [
        "- Key: Back Button\n- KeyPress: a",  # Mouse Gestures mode is still diverted for Key
        "- KeyIsDown: Back Button\n- KeyPress: a",
        "- Not: {Key: Forward Button}\n- KeyPress: a",  # a negated key does not need diverting
        "- Device: AAAA0001\n- Key: Forward Button\n- KeyPress: a",  # the keyboard has no Forward Button
        "- Key: Smart Shift\n- KeyPress: a",  # no device has it: HL002's case
        "- Key: G1\n- KeyPress: a",  # G keys come from the GKEY feature
        "- Key: Not A Real Key\n- KeyPress: a",
    ],
)
def test_undiverted_key_not_reported(rule):
    assert _found(_lint(rule), "HL001") == []


def test_control_that_cannot_be_diverted():
    (p,) = _found(_lint("- Key: Left Button\n- KeyPress: a"), "HL001")
    assert "cannot be diverted" in p.message and p.fix is None


def test_mouse_gesture_control_not_in_gesture_mode():
    (p,) = _found(_lint("- MouseGesture: [Middle Button, Mouse Up]\n- KeyPress: a"), "HL001")
    assert "Middle Button is not set to Mouse Gestures" in p.message
    assert p.fix.command[-2:] == ("Middle Button", "Mouse Gestures")


def test_mouse_gesture_needs_saved_gesture_mode():
    mouse = next(d for d in CTX.devices if d.device.serial == "AAAA0002")
    controls = [
        replace(c, mode=DivertMode.DIVERTED_MODE_UNKNOWN, saved_mode=DivertMode.DIVERTED)
        if c.name == "Back Button"
        else c
        for c in mouse.controls
    ]
    ctx = replace(CTX, devices=(replace(mouse, controls=tuple(controls)),))
    (p,) = _found(_lint("- MouseGesture: [Back Button, Mouse Up]\n- KeyPress: a", ctx=ctx), "HL001")
    assert "Back Button on Signature M650 Mouse: Diverted" in p.message


def test_mouse_gesture_with_unknown_saved_mode_is_not_reported():
    mouse = next(d for d in CTX.devices if d.device.serial == "AAAA0002")
    controls = [replace(c, saved_mode=None) if c.name == "Back Button" else c for c in mouse.controls]
    ctx = replace(CTX, devices=(replace(mouse, controls=tuple(controls)),))
    assert _found(_lint("- MouseGesture: [Back Button, Mouse Up]\n- KeyPress: a", ctx=ctx), "HL001") == []


def test_unread_mode_is_not_reported():
    mouse = next(d for d in CTX.devices if d.device.serial == "AAAA0002")
    controls = tuple(replace(c, mode=None) if c.divertable else c for c in mouse.controls)
    ctx = replace(CTX, devices=(replace(mouse, controls=controls),))
    rules = ("- Key: Forward Button\n- KeyPress: a", "- MouseGesture: [Middle Button, Mouse Up]\n- KeyPress: b")
    assert _found(_lint(*rules, ctx=ctx), "HL001") == []


def test_mouse_gesture_without_initiating_control():
    rule = "- MouseGesture: [Mouse Up, Mouse Down]\n- KeyPress: a"
    assert _found(_lint(rule), "HL001") == []  # Back Button is in Mouse Gestures mode
    (p,) = _found(_lint(rule, ctx=CTX_1120), "HL001")
    assert p.message.startswith("no control is set to Mouse Gestures")
    assert p.fix.command[-1] == "Mouse Gestures"


def test_undiverted_skipped_with_note_without_device_data():
    problems = lint_text(_rules("- Key: Forward Button\n- KeyPress: a"), NO_DEVICES)
    assert _found(problems, "HL001") == [p for p in problems if p.code == "HL001"]
    (note,) = _found(problems, "HL001")
    assert note.severity is Severity.NOTE and "skipped" in note.message


def test_client_errors_become_notes():
    class Broken(FakeSolaar):
        def devices(self):
            raise SolaarCommandError("could not run solaar (no such file)", ("solaar", "show"))

        def version(self):
            raise SolaarCommandError("could not run solaar (no such file)", ("solaar", "--version"))

    ctx = LintContext.from_client(Broken(), env={})
    assert ctx.version is None and ctx.devices is None
    assert "could not read devices" in ctx.devices_unavailable
    notes = [p for p in lint_text(_rules("- Key: Back Button"), ctx) if p.severity is Severity.NOTE]
    assert len(notes) == 3 and "Solaar version" in notes[0].message


# HL002


def test_renamed_control_on_older_solaar():
    (p,) = _found(_lint("- Key: Dictation\n- KeyPress: a"), "HL002")
    assert p.severity is Severity.ERROR
    assert "'Dictation' is not a control name Solaar 1.1.14 knows" in p.message
    assert p.fix.replacement == Key("Voice Dictation", None, listed=False)
    assert "Solaar 1.1.20's name" in p.fix.description


def test_renamed_control_on_newer_solaar():
    (p,) = _found(_lint("- Key: [Voice Dictation, released]\n- KeyPress: a", ctx=CTX_1120), "HL002")
    assert p.severity is Severity.ERROR
    assert p.fix.replacement == Key("Dictation", "released")


def test_name_whose_meaning_changed_in_1_1_15():
    # 1.1.14's Play/Pause is another control; the keyboard's key is Play/Pause Fn there, Play/Pause in 1.1.20.
    (p,) = _found(_lint("- Key: Play/Pause\n- KeyPress: a"), "HL002")
    assert p.severity is Severity.WARNING
    assert "'Play/Pause' is Solaar 1.1.20's name for the control Solaar 1.1.14 calls 'Play/Pause Fn'" in p.message
    assert p.fix.replacement.key == "Play/Pause Fn"


def test_control_name_is_case_sensitive():
    (p,) = _found(_lint("- Key: back button\n- KeyPress: a"), "HL002")
    assert p.fix.replacement.key == "Back Button" and "case-sensitively" in p.fix.description


def test_mouse_gesture_compares_printed_names():
    (p,) = _found(_lint("- MouseGesture: [Back_Button, Mouse Up]\n- KeyPress: a"), "HL002")
    assert p.fix.replacement == MouseGesture(["Back Button", "Mouse Up"], listed=True)
    (p,) = _found(_lint("- MouseGesture: [Back Button, Mouse up]\n- KeyPress: a"), "HL002")
    assert "'Mouse up' is not a movement or a control name" in p.message


def test_control_no_connected_device_has():
    (p,) = _found(_lint("- Key: Smart Shift\n- KeyPress: a"), "HL002")
    assert p.severity is Severity.WARNING and "no connected device" in p.message


def test_unknown_version_names_each_version():
    ctx = replace(CTX, version=None)
    (p,) = _found(_lint("- Key: Dictation\n- KeyPress: a", ctx=ctx), "HL002")
    assert p.severity is Severity.WARNING and "Solaar 1.1.14" in p.message
    (p,) = _found(_lint("- Key: Not A Real Key\n- KeyPress: a", ctx=ctx), "HL002")
    assert p.severity is Severity.ERROR


def test_version_between_pinned_tags_is_a_warning():
    ctx = replace(CTX_1120, version=(1, 1, 17))
    (p,) = _found(_lint("- Key: Voice Dictation\n- KeyPress: a", ctx=ctx), "HL002")
    assert p.severity is Severity.WARNING and "Checked against Solaar 1.1.20's names" in p.message


@pytest.mark.parametrize(
    "rule",
    [
        "- Key: Back_Button\n- KeyPress: a",
        "- Key: [Back Button, released]\n- KeyPress: a",
        "- Key: 'unknown:0053'\n- KeyPress: a",  # 0x53 is Back Button
        "- KeyIsDown: 'unknown:0053'\n- KeyPress: a",  # cannot tell; not reported
        "- MouseGesture: [Back Button, Mouse Up, Mouse Down-left]\n- KeyPress: a",
        "- MouseGesture: [Mouse Up, Back Button]\n- KeyPress: a",
        "- Key: G5\n- KeyPress: a",
    ],
)
def test_known_control_not_reported(rule):
    assert _found(_lint(rule), "HL002") == []


# HL003, HL004


def test_duplicate_binding():
    problems = _lint(
        "- Key: [Back Button, pressed]\n- Modifiers: [Control, Shift]\n- KeyPress: a",
        "- Modifiers: [Shift, Control]\n- Key: Back_Button\n- KeyPress: b",
    )
    (p,) = _found(problems, "HL003")
    assert p.rule_path == (1,) and "same trigger and conditions as rule 1" in p.message
    assert "never runs" in p.message
    assert _found(problems, "HL004") == []


def test_duplicate_binding_that_still_runs():
    (p,) = _found(
        _lint("- Key: Back Button\n- KeyPress: a\n- Test: crown_tap", "- Key: Back Button\n- KeyPress: b"), "HL003"
    )
    assert "never runs" not in p.message


@pytest.mark.parametrize(
    "rules",
    [
        ("- Key: Back Button\n- Modifiers: Control\n- KeyPress: a", "- Key: Back Button\n- KeyPress: b"),
        ("- Key: [Back Button, pressed]\n- KeyPress: a", "- Key: [Back Button, released]\n- KeyPress: b"),
        ("- Feature: CROWN\n- KeyPress: a\n- Test: crown_tap", "- Feature: CROWN\n- KeyPress: b"),  # no trigger
    ],
)
def test_not_duplicates(rules):
    assert _found(_lint(*rules), "HL003") == []


def test_unreachable_after_rule_with_fewer_conditions():
    problems = _lint(
        "- Key: Back Button\n- KeyPress: a",
        "- Key: Forward Button\n- KeyPress: b",
        "- Key: Back Button\n- Device: AAAA0002\n- KeyPress: c",
    )
    (p,) = _found(problems, "HL004")
    assert p.rule_path == (2,) and "rule 1 has a subset of its conditions" in p.message


def test_rule_without_conditions_shadows_everything_after():
    problems = _lint("- KeyPress: a", "- Key: Back Button\n- KeyPress: b", "- Feature: CROWN\n- KeyPress: c")
    assert _paths(problems, "HL004") == [(1,), (2,)]


def test_modifiers_shadow_only_without_actions_between():
    a = "- Key: Back Button\n- Modifiers: Control\n- KeyPress: a"
    b = "- Key: Back Button\n- Modifiers: Control\n- Feature: CROWN\n- KeyPress: b"
    assert _paths(_lint(a, "- Test: crown_tap", b), "HL004") == [(2,)]
    # A KeyPress between them could change the modifier state, so rule 3 might run.
    assert _paths(_lint(a, "- Key: Forward Button\n- KeyPress: Control_L", b), "HL004") == []


@pytest.mark.parametrize(
    "first",
    [
        "- Key: Back Button\n- KeyPress: a\n- Test: crown_tap",  # ends in a condition
        "- Key: Back Button\n- Process: firefox\n- KeyPress: a",  # focus can change between rules
        "- Key: Back Button\n- Setting: [null, dpi, 800]\n- KeyPress: a",
        "- Key: Back Button\n- Test: [thumb_wheel_up, 10]\n- KeyPress: a",  # changes Solaar state
        "- Key: Back Button\n- KeyPress: a\n- Bogus: 1",  # an unknown component is always false
        "- Key: Back Button\n- Rule: [KeyPress: a]",  # a sub-rule's result is not known
        "- Key: Back Button\n- Feature: CROWN\n- KeyPress: a",  # not a subset
        "- Key: Back Button\n- And: [KeyPress: a]\n- KeyPress: b",  # And runs actions
    ],
)
def test_not_unreachable(first):
    assert _found(_lint(first, "- Key: Back Button\n- Device: AAAA0002\n- KeyPress: b"), "HL004") == []


# HL005


def test_depress_without_release():
    (p,) = _found(
        _lint("- Key: Back Button\n- KeyPress: [[Super_L, Shift_L], depress]\n- KeyPress: [Shift_L, release]"), "HL005"
    )
    assert p.rule_path == (0, 1) and "depresses Super_L and" in p.message
    (p,) = _found(_lint("- Key: Back Button\n- MouseClick: [left, depress]"), "HL005")
    assert "button stays held down" in p.message


def test_release_in_another_rule_does_not_count():
    problems = _lint(
        "- Key: Back Button\n- KeyPress: [Super_L, depress]", "- Key: Back Button\n- KeyPress: [Super_L, release]"
    )
    assert _paths(problems, "HL005") == [(0, 1)]


@pytest.mark.parametrize(
    "rule",
    [
        "- Key: Back Button\n- KeyPress: [Super_L, depress]\n- Later: [1, KeyPress: [Super_L, release]]",
        "- Key: Back Button\n- KeyPress: [Super_L, click]\n- KeyPress: Super_L",
        "- Key: Back Button\n- MouseClick: [right, depress]\n- Rule: [MouseClick: [right, release]]",
    ],
)
def test_depress_with_release(rule):
    assert _found(_lint(rule), "HL005") == []


# HL006


def test_process_on_wayland_outside_gnome():
    ctx = _context(env=WAYLAND_KDE)
    problems = _lint("- Key: Back Button\n- Not: {MouseProcess: konsole}\n- Process: 42\n- KeyPress: a", ctx=ctx)
    assert _paths(problems, "HL006") == [(0, 1, 0), (0, 2)]
    assert all(p.severity is Severity.ERROR for p in _found(problems, "HL006"))


@pytest.mark.parametrize(
    "env",
    [X11, {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, {}],
)
def test_process_not_reported(env):
    assert _found(_lint("- Process: konsole\n- KeyPress: a", ctx=_context(env=env)), "HL006") == []


def test_session_from_env():
    assert Session.from_env({"WAYLAND_DISPLAY": "wayland-0"}) == Session(wayland=True, gnome=False)
    assert Session.from_env({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}).gnome
    assert Session.from_env({"XDG_SESSION_TYPE": "x11"}) == Session()


# HL007, HL008


def test_spaced_feature_name_by_version():
    problems = lint_file(RULES / "feature-names.yaml", CTX)
    (p,) = _found(problems, "HL007")
    assert p.rule_path == (1, 0) and p.severity is Severity.ERROR
    assert p.fix.replacement == Feature("THUMB_WHEEL")
    (p,) = _found(lint_file(RULES / "feature-names.yaml", CTX_1120), "HL007")
    assert p.severity is Severity.WARNING and "Solaar 1.1.14 loads" in p.message
    (p,) = _found(lint_file(RULES / "feature-names.yaml", LintContext()), "HL007")
    assert p.severity is Severity.WARNING


def test_spaced_feature_in_docs_example():
    problems = lint_file(RULES / "solaar-docs-example-fixed.yaml", CTX)
    assert _paths(problems, "HL007") == [(4, 0), (5, 0)]
    assert [p.fix.replacement.feature for p in _found(problems, "HL007")] == ["THUMB_WHEEL", "LOWRES_WHEEL"]


def test_spaced_name_that_is_no_feature():
    (p,) = _found(_lint("- Feature: NO SUCH"), "HL007")
    assert "'NO_SUCH' is not a Solaar feature name either" in p.message


def test_lost_feature():
    (p,) = _found(_lint("- Rule: [Feature: None, KeyPress: a]"), "HL008")
    assert (p.rule_path, p.severity, p.fix) == ((0, 0, 0), Severity.ERROR, None)
    assert "Pick the feature again" in p.message


@pytest.mark.parametrize("feature", ["THUMB_WHEEL", "CROWN", "none"])
def test_feature_names_not_reported(feature):
    problems = _lint(f"- Feature: {feature}\n- KeyPress: a", ctx=CTX_1120)
    assert _found(problems, "HL007") == _found(problems, "HL008") == []


# HL009


def test_load_abort_fixture():
    (p,) = _found(lint_file(RULES / "load-aborts.yaml", CTX), "HL009")
    assert (p.rule_path, p.severity) == ((1, 1), Severity.ERROR)
    assert "runs only the 1 rule before this one" in p.message and "the 1 rule after it" in p.message


def test_load_abort_only_on_newer_solaar():
    rule = "- Feature: 5\n- KeyPress: a"
    (p,) = _found(_lint(rule), "HL009")
    assert p.severity is Severity.WARNING and "the installed Solaar 1.1.14 can" in p.message
    assert _found(_lint(rule, ctx=CTX_1120), "HL009")[0].severity is Severity.ERROR
    assert _found(_lint(rule, ctx=LintContext()), "HL009")[0].severity is Severity.WARNING


def test_later_load_aborts_say_also():
    problems = _lint("- KeyPress: a", "- Test: mouse-up", "- MouseClick: []")
    assert [p.message.split(":")[0] for p in _found(problems, "HL009")] == [
        "Solaar 1.1.14 stops loading the rules file here",
        "Solaar 1.1.14 also cannot load this rule",
    ]


def test_null_document_aborts_load():
    (p,) = _found(_lint("- KeyPress: a", ""), "HL009")
    assert p.rule_path == (1,) and "null" in p.message


@pytest.mark.parametrize("rule", ["- Later: [500, MouseScroll: 5]", "- Key: 5", "- Test: [5]", "- Rule: abc"])
def test_no_load_abort(rule):
    assert _found(_lint(rule), "HL009") == []


# HL010


def test_collapse_hazards_fixture():
    problems = _found(lint_file(RULES / "collapse-hazards.yaml", CTX), "HL010")
    assert [p.rule_path for p in problems] == [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
    assert all(p.severity is Severity.WARNING for p in problems)


def test_malformed_args_fixture():
    problems = lint_file(RULES / "malformed-args.yaml", CTX)
    assert _paths(problems, "HL010") == [(0, 0), (0, 3), (1, 6)]


def test_underscore_feature_on_solaar_1_1_14():
    (p,) = _found(_lint("- Feature: THUMB_WHEEL\n- KeyPress: a"), "HL010")
    assert "writes this as 'THUMB WHEEL'" in p.message
    assert _found(_lint("- Feature: THUMB_WHEEL\n- KeyPress: a", ctx=CTX_1120), "HL010") == []


def test_unknown_component_breaks_solaar_save():
    (p,) = _found(_lint("- Key: Back Button\n- Rule: [Bogus: 1, KeyPress: a]"), "HL010")
    assert p.rule_path == (0, 1, 0) and "saving from Solaar's rule editor fails" in p.message


@pytest.mark.parametrize("fixture", ["argument-forms.yaml", "all-components.yaml", "lint-clean.yaml"])
def test_no_save_hazards(fixture):
    assert _found(lint_file(RULES / fixture, CTX_1120), "HL010") == []


# Paths and locations


def test_problem_paths_are_cut_back_to_the_model():
    ruleset = loads(_rules("- Not: [{Key: a}, {Bogus: 1}]"))
    assert model_path(ruleset, (0, 0, 0, 3)) == (0, 0)
    assert component_at(ruleset, (0, 0)).type_name == "Not"
    (p,) = _found(lint_text(_rules("- Not: [{Key: a}, {Bogus: 1}]"), CTX), "HL010")
    assert p.rule_path == (0, 0)


def test_locations():
    text = _rules(
        "- Key: Back Button\n- Not: {Process: x}\n- Later:\n  - 1\n  - KeyPress: a\n- Rule:\n  - Or: [Test: crown_tap]",
        "5",
    )
    ruleset = loads(text)
    lines = locations(text, ruleset)
    assert lines[(0,)] == 3
    assert [lines[p] for p in [(0, 0), (0, 1), (0, 1, 0), (0, 2), (0, 2, 0), (0, 3), (0, 3, 0), (0, 3, 0, 0)]] == [
        3,
        4,
        4,
        5,
        7,
        8,
        9,
        9,
    ]
    assert lines[(1,)] == 12


def test_fix_replacements_are_components():
    problems = lint_file(RULES / "lint-cases.yaml", CTX)
    replacements = [p.fix.replacement for p in problems if p.fix and p.fix.replacement is not None]
    assert replacements == [Key("Voice Dictation", None, listed=False)]


def test_controls_from_fake_have_the_fixture_modes():
    mouse = next(d for d in CTX.devices if d.device.serial == "AAAA0002")
    back = next(c for c in mouse.controls if c.name == "Back Button")
    assert isinstance(back, Control)
    assert (back.mode, back.saved_mode) == (DivertMode.DIVERTED_MODE_UNKNOWN, DivertMode.MOUSE_GESTURES)
