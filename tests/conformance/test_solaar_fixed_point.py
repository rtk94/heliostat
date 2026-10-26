# SPDX-License-Identifier: GPL-2.0-or-later
"""Solaar's own save is a fixed point: saving what it saved changes nothing."""

import pytest

from tests.conformance.harness import RULES_FIXTURES, SOLAAR_TAGS, solaar_roundtrip

FIXTURES = sorted(RULES_FIXTURES.glob("*.yaml"))

# (fixture name, tag) -> reason. Tag None means every tag. These are Solaar behaviors, not harness
# bugs; strict xfail so a change in Solaar shows up as an unexpected pass.
KNOWN_FAILURES = {
    ("solaar-docs-example.yaml", None): (
        "the published example has no '---' before the CROWN rule; PyYAML raises after 3 of 6 rules "
        "and Solaar logs the error and keeps only those 3"
    ),
    ("feature-names.yaml", "1.1.14"): (
        "1.1.14 saves Feature names with spaces (str(SupportedFeature)) but loads only the underscore "
        "spelling, so THUMB_WHEEL -> 'THUMB WHEEL' -> None"
    ),
    ("collapse-hazards.yaml", None): (
        "Solaar's save collapses TestBytes [1] to TestBytes: 1, and the next save crashes in TestBytes.data()"
    ),
    ("load-aborts.yaml", None): "MouseScroll: 5 makes Solaar's load raise; it logs the error and keeps 1 of 3 rules",
}


def _params():
    for tag in SOLAAR_TAGS:
        for fixture in FIXTURES:
            reason = KNOWN_FAILURES.get((fixture.name, tag)) or KNOWN_FAILURES.get((fixture.name, None))
            marks = [pytest.mark.xfail(reason=reason, strict=True)] if reason else []
            yield pytest.param(tag, fixture, id=f"{tag}-{fixture.stem}", marks=marks)


@pytest.mark.conformance
@pytest.mark.parametrize(("tag", "fixture"), list(_params()))
def test_solaar_save_is_fixed_point(tag, fixture, tmp_path):
    first = solaar_roundtrip(tag, fixture, tmp_path / "first.yaml")
    second = solaar_roundtrip(tag, tmp_path / "first.yaml", tmp_path / "second.yaml")
    assert second == first
