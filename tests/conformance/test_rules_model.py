# SPDX-License-Identifier: GPL-2.0-or-later
"""Heliostat's dumps() checked against real Solaar, on every rules fixture that parses."""

import pytest

from heliostat.rulesfile import RulesParseError, dumps, load
from tests.conformance.deviations import formatting_differences
from tests.conformance.harness import RULES_FIXTURES, SOLAAR_TAGS, solaar_dump_data, solaar_roundtrip
from tests.conformance.strict import assert_same_data


def _parses(path):
    try:
        load(path)
    except RulesParseError:
        return False
    return True


PARSEABLE = [f for f in sorted(RULES_FIXTURES.glob("*.yaml")) if _parses(f)]

# Valid YAML that makes every tag's load raise partway; Solaar keeps only the rules before it.
LOAD_ABORTS = {"load-aborts.yaml"}

# (fixture, tag) -> (reason, [(rule index, component data)]): forms that tag misloads. Heliostat's
# output must load exactly the same way on that tag, neither fixed nor made worse; the listed
# components confirm the misload is really there on both sides.
MISLOADS = {
    ("feature-names.yaml", "1.1.14"): (
        "1.1.14 loads the spaced name THUMB WHEEL as None (SupportedFeature[name], underscores only)",
        [(1, {"Feature": "None"})],
    ),
    ("solaar-docs-example-fixed.yaml", "1.1.14"): (
        "1.1.14 loads the spaced names THUMB WHEEL and LOWRES WHEEL as None",
        [(4, {"Feature": "None"}), (5, {"Feature": "None"})],
    ),
}


def _cases(skip=()):
    for tag in SOLAAR_TAGS:
        for fixture in PARSEABLE:
            marks = [pytest.mark.skip(reason=skip[fixture.name])] if fixture.name in skip else []
            yield pytest.param(tag, fixture, id=f"{tag}-{fixture.stem}", marks=marks)


@pytest.mark.conformance
@pytest.mark.parametrize(("tag", "fixture"), list(_cases()))
def test_solaar_loads_dumps_output_as_original(tag, fixture, tmp_path):
    """The hard rule: Solaar <tag> loads Heliostat's output exactly as it loads the original."""
    out = tmp_path / "heliostat.yaml"
    out.write_text(dumps(load(fixture)))
    load_error = fixture.name in LOAD_ABORTS
    expected = solaar_dump_data(tag, fixture, load_error=load_error)
    actual = solaar_dump_data(tag, out, load_error=load_error)
    assert_same_data(actual, expected)

    _reason, misloaded = MISLOADS.get((fixture.name, tag), (None, []))
    for index, component in misloaded:
        assert component in expected[index]["Rule"]
        assert component in actual[index]["Rule"]


# Byte comparisons only run on Solaar-canonical input (docs/decisions.md, "Formatting tests
# restructured"); fixtures as written are covered by the semantic test above and by the idempotence
# and D2 shape test in tests/test_rulesfile.py.
_SOLAAR_CANNOT_RESAVE = {
    **{name: "Solaar's load raises partway; its save would drop rules" for name in LOAD_ABORTS},
    "collapse-hazards.yaml": "Solaar's save of this file is one that its next save crashes on",
}


@pytest.mark.conformance
@pytest.mark.parametrize(("tag", "fixture"), list(_cases(skip=_SOLAAR_CANNOT_RESAVE)))
def test_dumps_matches_solaar_save_of_solaar_saved_file(tag, fixture, tmp_path):
    """On a file Solaar saved itself (argument shapes already as data() writes them), dumps() equals
    Solaar's next save, up to the documented deviations."""
    saved = tmp_path / "saved.yaml"
    solaar_roundtrip(tag, fixture, saved)
    heliostat = dumps(load(saved))
    solaar = solaar_roundtrip(tag, saved, tmp_path / "resaved.yaml").decode()
    diff = formatting_differences(heliostat, solaar, tag)
    assert diff is None, f"differs from Solaar {tag}'s save beyond the documented deviations:\n{diff}"
