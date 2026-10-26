# SPDX-License-Identifier: GPL-2.0-or-later
"""The GUI's Qt-free parts: rule text, advanced-tree rows, and reading Solaar in steps."""

import subprocess
from pathlib import Path

import pytest

from heliostat.analysis import component_at
from heliostat.model import Raw
from heliostat.rulesfile import RulesParseError, load, loads
from heliostat.solaar import CliSolaarClient, FakeSolaar, SolaarCommandError
from heliostat.ui.solaar_state import SolaarState, read_solaar, status_lines
from heliostat.ui.text import compact, flow, rule_nodes, rule_summary

FIXTURES = Path(__file__).parent / "fixtures"
SHOW = FIXTURES / "solaar" / "1.1.14" / "show_all_back-gestures.txt"


def _rule(text):
    (rule,) = loads(text).rules
    return rule


def test_simple_rule_is_described():
    rule = _rule("- Key: [Back Button, pressed]\n- Device: AAAA0002\n- KeyPress: [Control_L, Tab]\n")
    assert rule_summary(rule) == "When Back Button on AAAA0002 is pressed: press Ctrl+Tab"
    assert rule_summary(rule, {"AAAA0002": "Signature M650 Mouse"}) == (
        "When Back Button on Signature M650 Mouse is pressed: press Ctrl+Tab"
    )


def test_other_rules_get_the_compact_form():
    rule = _rule(
        "- Feature: THUMB WHEEL\n"
        "- Not: {Process: firefox}\n"
        "- Or: [{Test: thumb_wheel_up}, {Test: [thumb_wheel_down, 10]}]\n"
        "- Later: [1.5, {KeyPress: a}, {MouseScroll: [0, 1]}]\n"
        "- Frobnicate: {x: 1}\n"
    )
    assert rule_summary(rule) == (
        "Feature: THUMB WHEEL; Not(Process: firefox); Or(Test: thumb_wheel_up, Test: [thumb_wheel_down, 10]); "
        "Later(1.5: KeyPress: a; MouseScroll: [0, 1]); Frobnicate: {x: 1}"
    )


def test_compact_shows_arguments_as_loaded():
    # Scalar types are kept: a serial loaded as an int is not shown as a string, and vice versa.
    assert compact(_rule("- Device: 12345678\n").components[0]) == "Device: 12345678"
    assert compact(_rule("- Device: '12345678'\n").components[0]) == "Device: '12345678'"
    assert compact(_rule("- KeyPress: [[a], depress]\n").components[0]) == "KeyPress: [[a], depress]"
    assert compact(_rule("- Later: 2\n").components[0]) == "Later(2)"


def test_odd_documents():
    assert rule_summary(_rule("[]\n")) == "(empty rule)"
    assert rule_summary(loads("--- 5\n").rules[0]) == "(not a list of components) 5"
    assert flow(None) == "null"
    assert flow("text") == "text"


def test_tree_rows():
    rule = _rule("- Not: [{Key: [Back Button, released]}]\n- Later: [2, {KeyPress: a}]\n- 7\n")
    nodes = rule_nodes(rule, 4)
    assert [(n.path, n.label, n.value) for n in nodes] == [
        ((4, 0), "Not", ""),
        ((4, 1), "Later", "after 2 s"),
        ((4, 2), "(unrecognized)", "7"),
    ]
    assert [(c.path, c.label, c.value) for c in nodes[0].children] == [((4, 0, 0), "Key", "[Back Button, released]")]
    assert [(c.path, c.label, c.value) for c in nodes[1].children] == [((4, 1, 0), "KeyPress", "a")]
    assert nodes[2].unrecognized and "kept as written" in nodes[2].tooltip
    (top,) = rule_nodes(loads("--- {a: 1}\n").rules[0], 0)
    assert (top.path, top.label, top.value, top.unrecognized) == ((0,), "(not a rule)", "{a: 1}", True)


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.children)


@pytest.mark.parametrize("path", sorted((FIXTURES / "rules").glob("*.yaml")), ids=lambda p: p.name)
def test_tree_paths_are_problem_paths(path):
    """Every row's path finds its component the way lint's rule paths do (Problem.rule_path)."""
    try:
        ruleset = load(path)
    except RulesParseError:
        pytest.skip("not valid YAML")
    for i, rule in enumerate(ruleset.rules):
        for node in _walk(rule_nodes(rule, i)):
            component = component_at(ruleset, node.path)
            if isinstance(component, Raw):
                assert node.unrecognized
            elif len(node.path) > 1:
                assert node.label == component.TYPE


def test_read_solaar_reports_in_steps_and_asks_once():
    class Counting(FakeSolaar):
        calls: list = []

        def version(self):
            self.calls.append("version")
            return super().version()

        def devices(self):
            self.calls.append("devices")
            return super().devices()

        def controls(self, device):
            self.calls.append(("controls", device.name))
            return super().controls(device)

    client = Counting.from_show(SHOW.read_text(), version=(1, 1, 14))
    reports = []
    final = read_solaar(client, reports.append, env={})
    assert [(r.version, r.running, r.devices is not None, r.done) for r in reports] == [
        ((1, 1, 14), True, False, False),
        ((1, 1, 14), True, True, False),
    ]
    assert final.done and final.context.version == (1, 1, 14)
    assert client.calls == [
        "version",
        "devices",
        ("controls", "MX Mechanical"),
        ("controls", "Signature M650 Mouse"),
    ]
    assert client.refresh_calls == 1
    assert {d.name for d in final.controls} == {"MX Mechanical", "Signature M650 Mouse"}
    assert final.device_names == {"AAAA0001": "MX Mechanical", "AAAA0002": "Signature M650 Mouse"}
    assert status_lines(final) == ["Solaar 1.1.14"]


def test_read_solaar_runs_show_once_for_all_devices():
    """End to end through CliSolaarClient, with a counting stub for the subprocess layer."""
    outputs = {("solaar", "--version"): "solaar 1.1.14\n", ("solaar", "show"): SHOW.read_text()}
    calls = []

    def runner(argv, timeout, env):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 0, outputs[tuple(argv)], "")

    class NoSystem:
        def solaar_processes(self):
            return []

    client = CliSolaarClient(runner=runner, system=NoSystem())
    first = read_solaar(client, lambda state: None, env={})
    assert len(first.controls) == 2  # two online devices, controls for both
    assert calls == [("solaar", "--version"), ("solaar", "show")]
    read_solaar(client, lambda state: None, env={})  # a new read refreshes: show runs again, once
    assert calls.count(("solaar", "show")) == 2


def test_read_solaar_without_solaar():
    class Missing(FakeSolaar):
        def version(self):
            raise SolaarCommandError("could not run solaar ([Errno 2] No such file or directory)", ("solaar",))

        devices = version

    final = read_solaar(Missing(running=False), lambda state: None, env={})
    assert final.solaar_missing and final.devices is None and final.context.devices is None
    (line,) = status_lines(final)
    assert line.startswith("Solaar not found (could not run solaar")


def test_read_solaar_when_controls_fail():
    class NoControls(FakeSolaar):
        def controls(self, device):
            raise SolaarCommandError("timed out after 60.0 s", ("solaar", "show"))

    final = read_solaar(NoControls.from_show(SHOW.read_text()), lambda state: None, env={})
    assert len(final.devices) == 4 and final.controls == {}
    assert final.controls_error.startswith("could not read devices from Solaar: timed out")


def test_status_while_waiting():
    assert status_lines(SolaarState()) == ["Reading devices from Solaar…"]
    assert status_lines(SolaarState(version=(1, 1, 20), running=False, devices=())) == [
        "Solaar 1.1.20",
        "Solaar is not running, so no rules are active.",
        "No devices found.",
    ]
