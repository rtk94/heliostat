# SPDX-License-Identifier: GPL-2.0-or-later
"""Simple rules Heliostat builds: real Solaar loads them as held and saves them byte-for-byte the same.

Control names are limited to ones both pinned versions know, so expected_data() holds.
"""

import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from heliostat.model import RuleSet
from heliostat.rulesfile import dumps
from heliostat.simple import generate
from tests.conformance.deviations import formatting_differences
from tests.conformance.harness import SOLAAR_TAGS, solaar_dump_data, solaar_roundtrip
from tests.conformance.strict import assert_same_data
from tests.conformance.test_property import CONTROLS, PROPERTY_SETTINGS, _json_normalized, expected_data
from tests.test_simple import new_simple_rules


@pytest.mark.conformance
@settings(PROPERTY_SETTINGS, max_examples=25)
@given(new_simple_rules(st.sampled_from(CONTROLS)))
def test_solaar_loads_and_saves_new_simple_rules_unchanged(simple):
    ruleset = RuleSet([generate(simple)])
    heliostat = dumps(ruleset)
    expected = _json_normalized([expected_data(r) for r in ruleset.rules])
    with tempfile.TemporaryDirectory(prefix="heliostat-simple-") as tmp:
        path = Path(tmp) / "rules.yaml"
        path.write_text(heliostat)
        for tag in SOLAAR_TAGS:
            assert_same_data(solaar_dump_data(tag, path), expected)
            solaar = solaar_roundtrip(tag, path, Path(tmp) / f"solaar-{tag}.yaml").decode()
            diff = formatting_differences(heliostat, solaar, tag)
            assert diff is None, f"differs from Solaar {tag}'s save beyond the documented deviations:\n{diff}"
