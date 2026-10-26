# SPDX-License-Identifier: GPL-2.0-or-later
"""model.edit: edits by rule path return a new RuleSet and leave everything else as loaded."""

import copy
import textwrap

import pytest

from heliostat.model import Key, KeyPress, Not, Process, Raw, Rule, edit
from heliostat.rulesfile import dumps, loads

TEXT = textwrap.dedent("""\
    ---
    - Key: Back Button
    - Not: [Process: kwin]
    - Or:
      - Modifiers: [Shift]
      - Foo: [1, 2]
    - Later: [0.5, KeyPress: a, Execute: [notify-send, done]]
    ...
    ---
    just a string
    ...
    """)


@pytest.fixture
def ruleset():
    return loads(TEXT)


def test_get(ruleset):
    assert edit.get(ruleset, (0, 0)) == Key("Back Button", None, listed=False)
    assert edit.get(ruleset, (0, 1, 0)) == Process("kwin")
    assert edit.get(ruleset, (0, 2, 1)) == Raw({"Foo": [1, 2]})
    assert edit.get(ruleset, (0, 3, 0)) == KeyPress(["a"], None, edit.get(ruleset, (0, 3, 0)).form)
    assert isinstance(edit.get(ruleset, (1,)), Raw)
    for bad in [(0, 9), (0, 1, 1), (0, 0, 0), (5,), ()]:
        with pytest.raises(edit.EditError):
            edit.get(ruleset, bad)


def test_edits_do_not_touch_the_original(ruleset):
    before = copy.deepcopy(ruleset)
    edit.replace(ruleset, (0, 0), Key("Forward Button"))
    edit.insert(ruleset, (0, 2, 0), Process("firefox"))
    edit.remove(ruleset, (0, 3, 1))
    edit.move(ruleset, (0, 0), 1)
    assert dumps(ruleset) == dumps(before)


def test_replace_keeps_siblings_as_loaded(ruleset):
    out = edit.replace(ruleset, (0, 0), Key("Forward Button"))
    assert dumps(out) == dumps(ruleset).replace("- Key: Back Button\n", "- Key: [Forward Button, pressed]\n")


def test_replace_inside_not(ruleset):
    out = edit.replace(ruleset, (0, 1, 0), Process("firefox"))
    assert edit.get(out, (0, 1)) == Not(Process("firefox"), listed=True)


def test_replace_top_level_needs_a_rule(ruleset):
    out = edit.replace(ruleset, (1,), Rule([Process("x")]))
    assert out.rules[1] == Rule([Process("x")])
    with pytest.raises(edit.EditError):
        edit.replace(ruleset, (1,), Process("x"))


def test_insert(ruleset):
    out = edit.insert(ruleset, (0, 2, 2), Process("firefox"))
    assert edit.get(out, (0, 2, 2)) == Process("firefox")
    out = edit.insert(ruleset, (0, 3, 0), KeyPress(["b"]))
    assert [type(c).__name__ for c in edit.get(out, (0, 3)).components] == ["KeyPress", "KeyPress", "Execute"]
    assert edit.get(out, (0, 3)).delay == 0.5
    out = edit.insert(ruleset, (2,), Rule([]))
    assert len(out.rules) == 3
    for bad in [(0, 1, 1), (0, 0, 0), (0, 9)]:
        with pytest.raises(edit.EditError):
            edit.insert(ruleset, bad, Process("x"))


def test_remove(ruleset):
    out = edit.remove(ruleset, (0, 2, 1))
    assert edit.get(out, (0, 2)).components == [edit.get(ruleset, (0, 2, 0))]
    out = edit.remove(ruleset, (1,))
    assert len(out.rules) == 1
    assert not edit.can_remove(ruleset, (0, 1, 0))  # the component inside a Not
    with pytest.raises(edit.EditError):
        edit.remove(ruleset, (0, 1, 0))


def test_move(ruleset):
    out, path = edit.move(ruleset, (0, 3, 1), -1)
    assert path == (0, 3, 0)
    assert [c.TYPE for c in edit.get(out, (0, 3)).components] == ["Execute", "KeyPress"]
    out, path = edit.move(ruleset, (1,), -1)
    assert path == (0,) and isinstance(out.rules[0], Raw)
    assert not edit.can_move(ruleset, (0, 0), -1)
    assert not edit.can_move(ruleset, (0, 3), 1)
    assert not edit.can_move(ruleset, (0, 1, 0), 1)
    with pytest.raises(edit.EditError):
        edit.move(ruleset, (0, 0), -1)
