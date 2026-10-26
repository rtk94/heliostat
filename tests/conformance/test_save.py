# SPDX-License-Identifier: GPL-2.0-or-later
"""The editor's save path against real Solaar: edit a file Solaar saved, write it with rulesfile.save,
and Solaar loads exactly the edited rules and saves them byte-for-byte the same (up to D1).

The edits are the ones the rule list and the simple editor make: move, duplicate, delete, insert a new
simple rule, and replace a rule with an edited simple rule. Solaar's view of the result is predicted
from its view of the unedited file, edited the same way.
"""

import copy

import pytest

from heliostat.model import CLICK, Key, KeyPress, MouseClick, RuleSet, edit
from heliostat.rulesfile import dumps, load, save
from heliostat.simple import KeyTrigger, SimpleRule, generate, recognize
from tests.conformance.deviations import formatting_differences
from tests.conformance.harness import SOLAAR_TAGS, solaar_dump_data, solaar_roundtrip
from tests.conformance.strict import assert_same_data
from tests.conformance.test_property import _json_normalized, expected_data
from tests.conformance.test_rules_model import _SOLAAR_CANNOT_RESAVE, PARSEABLE

NEW_RULE = generate(SimpleRule(KeyTrigger("Back Button"), [KeyPress(["Control_L", "Tab"], CLICK)], process="kitty"))


def _edits(ruleset: RuleSet, data: list) -> tuple[RuleSet, list]:
    """Edit both the model and Solaar's data() of it the same way."""
    data = copy.deepcopy(data)
    n = len(ruleset.rules)
    if n >= 2:
        ruleset, _ = edit.move(ruleset, (n - 1,), -1)
        data.insert(n - 2, data.pop(n - 1))
        ruleset = edit.insert(ruleset, (1,), ruleset.rules[0])
        data.insert(1, copy.deepcopy(data[0]))
        ruleset = edit.remove(ruleset, (2,))
        del data[2]
    for i, rule in enumerate(ruleset.rules):
        simple = recognize(rule)
        if simple is not None and isinstance(simple.trigger, KeyTrigger):
            edited = generate(
                SimpleRule(
                    KeyTrigger("Forward Button", "released"),
                    [*simple.actions, MouseClick("middle", 2)],
                    device=simple.device,
                    modifiers=simple.modifiers,
                    process=simple.process,
                    written=simple.written,
                )
            )
            ruleset = edit.replace(ruleset, (i,), edited)
            rule_data = data[i]["Rule"]
            trigger = next(k for k, c in enumerate(rule_data) if "Key" in c)
            rule_data[trigger] = expected_data(Key("Forward Button", "released"))
            rule_data.append(expected_data(MouseClick("middle", 2)))
            break
    ruleset = edit.insert(ruleset, (len(ruleset.rules),), NEW_RULE)
    data.append(expected_data(NEW_RULE))
    return ruleset, _json_normalized(data)


def _cases():
    for tag in SOLAAR_TAGS:
        for fixture in PARSEABLE:
            if fixture.name not in _SOLAAR_CANNOT_RESAVE:
                yield pytest.param(tag, fixture, id=f"{tag}-{fixture.stem}")


@pytest.mark.conformance
@pytest.mark.parametrize(("tag", "fixture"), list(_cases()))
def test_edited_save_loads_as_held_and_matches_solaar_save(tag, fixture, tmp_path):
    path = tmp_path / "rules.yaml"
    solaar_roundtrip(tag, fixture, path)  # a file as Solaar saved it
    loaded_bytes = path.read_bytes()
    ruleset, expected = _edits(load(path), solaar_dump_data(tag, path))

    result = save(path, dumps(ruleset), loaded_bytes)
    assert result.written and result.backup.read_bytes() == loaded_bytes
    assert_same_data(solaar_dump_data(tag, path), expected)
    heliostat = path.read_text()
    solaar = solaar_roundtrip(tag, path, tmp_path / "resaved.yaml").decode()
    diff = formatting_differences(heliostat, solaar, tag)
    assert diff is None, f"differs from Solaar {tag}'s save beyond the documented deviations:\n{diff}"
