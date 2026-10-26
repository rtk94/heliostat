# SPDX-License-Identifier: GPL-2.0-or-later
"""Lint's claims about Solaar, checked against the pinned Solaar checkouts.

- HL009: analysis.solaar_model.load_abort predicts, for every case below, exactly whether each tag's
  _load_rule_config raises on the document (keeping only the rules before it).
- HL010: analysis.solaar_model.save_hazards reports a hazard for exactly the cases where Solaar's own
  save damages the rule, and the damage is the kind the case states.
- HL003 / HL004 / HL006: Solaar stops processing after a top-level rule that ends in an action, or
  whose condition returns None (Process without focus information); a rule ending in a condition
  does not stop it.
"""

import json

import pytest
import yaml

from heliostat.analysis.solaar_model import load_abort, save_hazards
from tests.conformance.harness import SOLAAR_TAGS, run_runner

BOTH = frozenset(SOLAAR_TAGS)
NEWER = frozenset({"1.1.20"})

# (document text, tags whose load raises on it)
LOAD_CASES = [
    ("- MouseScroll: 5", BOTH),
    ("", BOTH),  # a null document
    ("5", BOTH),
    ("true", BOTH),
    ("- Rule: 5", BOTH),
    ("- Or: null", BOTH),
    ("- And: 3", BOTH),
    ("- Feature: [CROWN]", BOTH),
    ("- Feature: {CROWN: 1}", BOTH),
    ("- Feature: 5", NEWER),
    ("- Feature: null", NEWER),
    ("- Feature: true", NEWER),
    ("- Modifiers: null", BOTH),
    ("- Modifiers: [[Shift]]", BOTH),
    ("- Key: 'unknown:zz'", BOTH),
    ("- Key: ['unknown:', released]", BOTH),
    ("- Test: mouse-up", BOTH),
    ("- Test: [mouse-down, 1]", BOTH),
    ("- Test: [[crown_tap]]", BOTH),
    ("- MouseGesture: 5", BOTH),
    ("- KeyPress: [5, click]", BOTH),
    ("- KeyPress: [null, depress]", BOTH),
    ("- KeyPress: [[a, b]]", BOTH),
    ("- KeyPress: {a: b}", BOTH),
    ("- MouseScroll: null", BOTH),
    ("- MouseScroll: {a: 1}", BOTH),
    ("- MouseClick: 5", BOTH),
    ("- MouseClick: []", BOTH),
    ("- MouseClick: {a: 1}", BOTH),
    ("- MouseClick: [left, .inf]", BOTH),
    ("- Execute: 5", BOTH),
    ("- Execute: null", BOTH),
    ("- Rule: [MouseScroll: 5]", BOTH),
    ("- Not: [MouseScroll: 5]", BOTH),
    ("- Or: [Not: {Execute: 5}]", BOTH),
    ("- Later: [1, MouseScroll: 5]", BOTH),
    ("- Rule: [Rule: [Feature: 5]]", NEWER),
    # Loads (with warnings at most)
    ("- Later: [500, MouseScroll: 5]", frozenset()),  # invalid delay: Later compiles nothing
    ("- Later: [soon, Execute: 5]", frozenset()),
    ("abc", frozenset()),  # a string document: each character is an (always false) condition
    ("Key: Back Button", frozenset()),  # a mapping document: its keys are conditions
    ("- Rule: abc", frozenset()),
    ("- Rule: {MouseScroll: 5}", frozenset()),
    ("- Not: [a, b]", frozenset()),
    ("- Feature: NOT_A_FEATURE", frozenset()),
    ("- Feature: THUMB WHEEL", frozenset()),
    ("- Key: 5", frozenset()),
    ("- Key: [[Back Button]]", frozenset()),
    ("- Key: 'unknown:0053'", frozenset()),
    ("- Key: back button", frozenset()),
    ("- KeyIsDown: 5", frozenset()),
    ("- KeyIsDown: 'unknown:zz'", frozenset()),
    ("- Test: 5", frozenset()),
    ("- Test: []", frozenset()),
    ("- Test: [5]", frozenset()),
    ("- Test: [nonsense]", frozenset()),
    ("- MouseGesture: [[a]]", frozenset()),
    ("- MouseGesture: {a: b}", frozenset()),
    ("- Modifiers: {Shift: 1}", frozenset()),
    ("- MouseScroll: [1]", frozenset()),
    ("- MouseScroll: abc", frozenset()),
    ("- MouseScroll: {0: [1, 2]}", frozenset()),
    ("- MouseClick: x", frozenset()),
    ("- MouseClick: {}", frozenset()),
    ("- MouseClick: [left, .nan]", frozenset()),
    ("- MouseClick: [left, [2]]", frozenset()),
    ("- KeyPress: null", frozenset()),
    ("- KeyPress: [a, b]", frozenset()),
    ("- KeyPress: [[a], 5]", BOTH),  # not an action second, so every item is a key; [a] is unhashable
    ("- Execute: {a: b}", frozenset()),
    ("- Execute: [5]", frozenset()),
    ("- Process: [firefox]", frozenset()),
    ("- Setting: 5", frozenset()),
    ("- Set: [dpi]", frozenset()),
    ("- Report: x", frozenset()),
    ("- TestBytes: 1", frozenset()),
    ("- Device: [x]", frozenset()),
]

FIRST = "- Key: [Back Button, pressed]\n- KeyPress: [a, click]"
LAST = "- Key: [Forward Button, pressed]\n- KeyPress: [b, click]"


def _rules_file(*documents: str) -> str:
    return "%YAML 1.3\n" + "".join(f"---\n{d}\n...\n" for d in documents)


def _probe(tag, tmp_path, texts):
    paths = []
    for n, text in enumerate(texts):
        path = tmp_path / f"case{n:03}.yaml"
        path.write_text(text)
        paths.append(str(path))
    result = run_runner(tag, "probe", *paths)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.conformance
@pytest.mark.parametrize("tag", SOLAAR_TAGS)
def test_load_abort_predictions_match_solaar(tag, tmp_path):
    results = _probe(tag, tmp_path, [_rules_file(FIRST, doc, LAST) for doc, _ in LOAD_CASES])
    wrong = []
    for (doc, aborting), result in zip(LOAD_CASES, results, strict=True):
        solaar_aborts = result["load_errors"] > 0
        if solaar_aborts:
            assert result["kept"] == 1, (doc, result)  # the rule before it, nothing after
        else:
            assert result["kept"] == 3, (doc, result)
        predicted = load_abort(yaml.safe_load(f"---\n{doc}\n..."), tag) is not None
        expected = tag in aborting
        if not (solaar_aborts == predicted == expected):
            wrong.append(f"{doc!r}: Solaar aborts {solaar_aborts}, predicted {predicted}, case says {expected}")
    assert not wrong, "\n".join(wrong)
    assert any(tag in a for _, a in LOAD_CASES) and any(tag not in a for _, a in LOAD_CASES)


# (document text, {tag: damage}) with damage one of:
#   "save-fails"        Solaar's save raises or logs an error and leaves the file as it was
#   "changes-meaning"   the saved file loads as different rules
#   "next-load-aborts"  the saved file's load raises
#   "next-save-fails"   the saved file loads the same, but saving it again fails
#   "deletes:<text>"    the saved file loads the same, but <text> from the original is gone
# A tag that is not listed must save the rule harmlessly: it saves, reloads as the same rules, and
# saves again.
SAVE_CASES = [
    ("- Device: [MX Master 3]", {"*": "changes-meaning"}),
    ("- Active: [MX Master 3]", {"*": "changes-meaning"}),
    ("- Host: [workstation]", {"*": "changes-meaning"}),
    ("- Set: [null, dpi, [1600]]", {"*": "changes-meaning"}),
    ("- Setting: [null, dpi, [1600]]", {"*": "changes-meaning"}),
    ("- Test: [crown_tap, [1]]", {"*": "changes-meaning"}),
    ("- Execute: [[xflock4]]", {"*": "changes-meaning"}),
    ("- Execute: [notify-send, [hi]]", {"*": "changes-meaning"}),
    ("- Execute: [5]", {"*": "next-load-aborts"}),
    ("- Execute: [true]", {"*": "next-load-aborts"}),
    ("- TestBytes: [1]", {"*": "next-save-fails"}),
    ("- Test: [5]", {"*": "next-save-fails"}),
    ("- TestBytes: 1", {"*": "save-fails"}),
    ("- TestBytes: null", {"*": "save-fails"}),
    ("- Execute: {xflock4: 1}", {"*": "save-fails"}),
    ("- Bogus: 1", {"*": "save-fails"}),
    ("- {Key: Back Button, Test: crown_tap}", {"*": "save-fails"}),
    ("- just a string", {"*": "save-fails"}),
    ("- Rule: [Bogus: 1]", {"*": "save-fails"}),
    ("- Not: [{Key: Back Button}, {Test: crown_tap}]", {"*": "save-fails"}),
    ("- Later: [1, Bogus: 1]", {"*": "save-fails"}),
    ("abc", {"*": "save-fails"}),
    ("Key: Back Button", {"*": "save-fails"}),
    ("- Later: [500, KeyPress: XF86_AudioMute]", {"*": "deletes:XF86_AudioMute"}),
    ("- Later: [soon, KeyPress: XF86_AudioMute]", {"*": "deletes:XF86_AudioMute"}),
    ("- Set: [dpi, 1600]", {"*": "deletes:dpi"}),
    ("- Setting: [smart-shift]", {"*": "deletes:smart-shift"}),
    ("- Key: Not A Real Key", {"*": "deletes:Not A Real Key"}),
    ("- Key: [back button, released]", {"*": "deletes:back button"}),
    ("- KeyIsDown: Not A Real Key", {"*": "deletes:Not A Real Key"}),
    ("- KeyIsDown: [Back Button]", {"*": "deletes:Back Button"}),
    ("- Key: Voice Dictation", {"1.1.20": "deletes:Voice Dictation"}),
    ("- Key: Dictation", {"1.1.14": "deletes:Dictation"}),
    ("- Feature: NOT_A_FEATURE", {"*": "deletes:NOT_A_FEATURE"}),
    ("- Feature: THUMB_WHEEL", {"1.1.14": "changes-meaning"}),
    ("- Feature: HEADSET_EQ", {"1.1.14": "deletes:HEADSET_EQ"}),  # a feature 1.1.14 does not have
    # Harmless: Solaar's save rewrites these, but they load the same afterwards
    ("- Device: MX Master 3", {}),
    ("- Execute: [xflock4]", {}),
    ("- Modifiers: [Shift, Hyper]", {}),
    ("- Test: [nonsense]", {}),
    ("- Test: [crown_tap, null]", {}),
    ("- Report: x", {}),
    ("- Key: [Back Button, down]", {}),
    ("- Key: Back_Button", {}),
    ("- Key: 'unknown:0053'", {}),
    ("- MouseClick: [5]", {}),
    ("- MouseScroll: [1]", {}),
    ("- MouseScroll: [[0, 1]]", {}),
    ("- Later: [soon]", {}),
    ("- Later: [2, KeyPress: a]", {}),
    ("- KeyPress: [[Control_L], click]", {}),
    ("- KeyPress: [[click], click]", {}),
    ("- Not: [Key: Back Button]", {}),
    ("- Process: [firefox]", {}),
    ("- Feature: CROWN", {}),
    ("- Feature: None", {}),
    ("- Feature: THUMB WHEEL", {}),  # HL007's case, not HL010's: loads the same before and after
    ("- Set: []", {}),
    ("- Setting: [null, dpi, 1600]", {}),
]


def _no_key(data):
    """Key / KeyIsDown data() writes 'None' or '0' for a name that did not resolve; both mean no key."""
    if isinstance(data, list):
        return [_no_key(d) for d in data]
    if isinstance(data, dict):
        out = {k: _no_key(v) for k, v in data.items()}
        if "Key" in out and isinstance(out["Key"], list) and out["Key"][:1] == ["None"]:
            out["Key"] = ["0", *out["Key"][1:]]
        if out.get("KeyIsDown") == "None":
            out["KeyIsDown"] = "0"
        return out
    return data


def _damage(result, original):
    if not result["save_ok"]:
        assert result["file_unchanged"], result
        return "save-fails"
    if result["reload_errors"]:
        return "next-load-aborts"
    if not result["resave_ok"]:
        return "next-save-fails"
    if _no_key(result["reload_data"]) != _no_key(result["data"]):
        return "changes-meaning"
    return None


@pytest.mark.conformance
@pytest.mark.parametrize("tag", SOLAAR_TAGS)
def test_save_hazard_predictions_match_solaar(tag, tmp_path):
    texts = [_rules_file(doc) for doc, _ in SAVE_CASES]
    results = _probe(tag, tmp_path, texts)
    wrong = []
    for (doc, damages), text, result in zip(SAVE_CASES, texts, results, strict=True):
        assert result["load_errors"] == 0, (doc, result)
        expected = damages.get(tag, damages.get("*"))
        actual = _damage(result, text)
        if actual is None and expected is not None and expected.startswith("deletes:"):
            gone = expected.removeprefix("deletes:")
            if gone in text and gone not in result["saved_text"]:
                actual = expected
        predicted = bool(save_hazards(yaml.safe_load(f"---\n{doc}\n..."), tag))
        if actual != expected or predicted != (expected is not None):
            wrong.append(f"{doc!r}: Solaar {actual}, case says {expected}, predicted hazard {predicted}")
    assert not wrong, "\n".join(wrong)


# Evaluation: which KeyPress actions run for a press of Back Button.
EVALUATION_CASES = [
    # Processing stops after a rule that ends in an action (HL003, HL004).
    ([("- Key: [Back Button, pressed]\n- KeyPress: a"), "- Key: [Back Button, pressed]\n- KeyPress: b"], [["a"]]),
    (["- KeyPress: a", "- Key: [Back Button, pressed]\n- KeyPress: b"], [["a"]]),
    # ... but not after a rule whose conditions fail, or one that ends in a condition.
    (["- Key: [Forward Button, pressed]\n- KeyPress: a", "- Key: [Back Button, pressed]\n- KeyPress: b"], [["b"]]),
    (
        [
            "- Key: [Back Button, pressed]\n- KeyPress: a\n- Test: crown_tap",
            "- Key: [Back Button, pressed]\n- KeyPress: b",
        ],
        [["a"], ["b"]],
    ),
    # A sub-rule whose condition fails does not stop its parent; one ending in an action does.
    (["- Rule: [Test: crown_tap, KeyPress: a]\n- KeyPress: b", "- KeyPress: c"], [["b"]]),
    (["- Rule: [KeyPress: a]\n- KeyPress: b", "- KeyPress: c"], [["a"]]),
    # A condition that returns None (Process with no focus information) stops everything (HL006).
    (["- Key: [Back Button, pressed]\n- Process: firefox\n- KeyPress: a", "- KeyPress: b"], []),
    (["- Not: {Process: firefox}\n- KeyPress: a", "- KeyPress: b"], []),
]


@pytest.mark.conformance
@pytest.mark.parametrize("tag", SOLAAR_TAGS)
@pytest.mark.parametrize(("documents", "ran"), EVALUATION_CASES)
def test_evaluation_stops_where_lint_says(tag, documents, ran, tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(_rules_file(*documents))
    result = run_runner(tag, "evaluate", str(path), "Back Button")
    assert result.returncode in (0, 1), result.stderr  # warnings about missing X11 are logged, not errors
    assert json.loads(result.stdout) == ran, result.stderr
