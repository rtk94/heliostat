# SPDX-License-Identifier: GPL-2.0-or-later
"""Smoke tests for the read-only GUI, headless (QT_QPA_PLATFORM=offscreen, see conftest.py), with FakeSolaar."""

import threading
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QThreadPool

from heliostat import cli
from heliostat.analysis import Severity
from heliostat.solaar import FakeSolaar, SolaarCommandError
from heliostat.ui.main_window import PATH_ROLE, MainWindow

SHOW = Path(__file__).parent / "fixtures" / "solaar" / "1.1.14" / "show_all_back-gestures.txt"
ENV = {"XDG_SESSION_TYPE": "x11"}

RULES = """\
%YAML 1.3
---
- Key: [Back Button, pressed]
- KeyPress: [Control_L, Tab]
...
---
- Feature: THUMB_WHEEL
- Rule:
  - Test: thumb_wheel_up
  - KeyPress: XF86_AudioRaiseVolume
...
---
- Key: [Forward Button, pressed]
- KeyPress: [Alt_L, Left]
...
---
- Or:
  - Key: [Not A Control, pressed]
  - Key: [Back Button, released]
- KeyPress: a
...
"""


class GatedSolaar(FakeSolaar):
    """devices() waits until `gate` is set, like a slow `solaar show`."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gate = threading.Event()

    def devices(self):
        assert self.gate.wait(10), "test never opened the gate"
        return super().devices()


class MissingSolaar(FakeSolaar):
    """No `solaar` command on PATH."""

    def _missing(self, *args):
        raise SolaarCommandError("could not run solaar ([Errno 2] No such file or directory: 'solaar')", ("solaar",))

    version = devices = controls = _missing

    def is_running(self):
        return False


def _fake(cls=FakeSolaar):
    return cls.from_show(SHOW.read_text(), version=(1, 1, 14))


@pytest.fixture
def rules_file(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(RULES)
    return path


@pytest.fixture
def pool():
    pool = QThreadPool()
    yield pool
    assert pool.waitForDone(10_000)


@pytest.fixture
def open_window(qtbot, pool):
    def open_window(path, client, start=True):
        window = MainWindow(path, client, pool=pool, env=ENV)
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        if start:
            window.start_solaar()
        return window

    return open_window


def _rule_texts(window):
    return [window.rule_list.topLevelItem(i).text(1) for i in range(window.rule_list.topLevelItemCount())]


def _codes(window):
    """Codes of the findings, not of the notes about checks that could not run."""
    return [p.code for p in window.problems if p.severity is not Severity.NOTE]


def test_window_opens_and_lists_rules(qtbot, open_window, rules_file):
    window = open_window(rules_file, _fake())
    assert _rule_texts(window) == [
        "When Back Button is pressed: press Ctrl+Tab",
        "Feature: THUMB_WHEEL; Rule(Test: thumb_wheel_up; KeyPress: XF86_AudioRaiseVolume)",
        "When Forward Button is pressed: press Alt+Left",
        "Or(Key: [Not A Control, pressed], Key: [Back Button, released]); KeyPress: a",
    ]
    with qtbot.waitSignal(window.solaarLoaded, timeout=10_000):
        pass
    devices = [window.sidebar.tree.topLevelItem(i).text(0) for i in range(window.sidebar.tree.topLevelItemCount())]
    assert devices == ["MX Mechanical", "Signature M650 Mouse", "MX MCHNCL", "Logi M650"]
    assert "Solaar 1.1.14" in window.sidebar.status.text()
    # Forward Button is in Regular mode on the M650: only known once the devices are read.
    assert any(p.code == "HL001" and p.rule_path[0] == 2 for p in window.problems)
    assert "checked against Solaar 1.1.14" in window.statusBar().currentMessage()


def test_window_opens_before_solaar_answers(qtbot, open_window, rules_file):
    client = _fake(GatedSolaar)
    window = open_window(rules_file, client)
    try:
        assert window.rule_list.topLevelItemCount() == 4
        assert "HL002" in _codes(window)  # lint ran on the file alone
        assert "HL001" not in _codes(window)
        qtbot.waitUntil(lambda: "Reading devices" in window.sidebar.status.text(), timeout=5_000)
        assert window.sidebar.tree.topLevelItemCount() == 0
    finally:
        client.gate.set()
    with qtbot.waitSignal(window.solaarLoaded, timeout=10_000):
        pass
    assert window.sidebar.tree.topLevelItemCount() == 4
    assert "HL001" in _codes(window)


def test_clicking_a_problem_selects_its_rule(qtbot, open_window, rules_file):
    window = open_window(rules_file, _fake())
    with qtbot.waitSignal(window.solaarLoaded, timeout=10_000):
        pass
    row = next(i for i, p in enumerate(window.problems) if p.code == "HL002")
    assert window.problems[row].rule_path == (3, 0, 0)
    item = window.problem_list.topLevelItem(row)
    window.problem_list.scrollToItem(item)
    rect = window.problem_list.visualItemRect(item)
    qtbot.mouseClick(window.problem_list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())

    assert window.rule_list.currentItem() is window.rule_list.topLevelItem(3)
    assert window.rule_heading.text().startswith("Rule 4 (line 17): advanced (Or condition)")
    assert window.rule_tree.currentItem().data(0, PATH_ROLE) == (3, 0, 0)
    assert window.rule_tree.currentItem().text(1) == "[Not A Control, pressed]"
    assert "HL002" in window.problem_detail.text()


def test_selecting_a_rule_shows_its_tree(qtbot, open_window, rules_file):
    window = open_window(rules_file, _fake(), start=False)
    window.rule_list.setCurrentItem(window.rule_list.topLevelItem(1))
    tree = window.rule_tree
    assert [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())] == ["Feature", "Rule"]
    nested = tree.topLevelItem(1)
    assert [(nested.child(i).text(0), nested.child(i).text(1)) for i in range(nested.childCount())] == [
        ("Test", "thumb_wheel_up"),
        ("KeyPress", "XF86_AudioRaiseVolume"),
    ]


def test_solaar_missing_keeps_the_rest_usable(qtbot, open_window, rules_file):
    window = open_window(rules_file, _fake(MissingSolaar))
    with qtbot.waitSignal(window.solaarLoaded, timeout=10_000):
        pass
    assert "Solaar not found" in window.sidebar.status.text()
    assert window.sidebar.tree.topLevelItemCount() == 0
    assert window.rule_list.topLevelItemCount() == 4
    assert any(p.code == "HL001" and p.rule_path == () and "skipped" in p.message for p in window.problems)


def test_solaar_not_running_is_shown(qtbot, open_window, rules_file):
    client = _fake()
    client.running = False
    window = open_window(rules_file, client)
    with qtbot.waitSignal(window.solaarLoaded, timeout=10_000):
        pass
    assert "Solaar is not running" in window.sidebar.status.text()
    assert window.sidebar.tree.topLevelItemCount() == 4


def test_broken_yaml_is_reported(qtbot, open_window, tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("---\n- Key: [A, pressed]\n...\n---\n- Key: [B\n")
    window = open_window(path, _fake(), start=False)
    assert window.banner.isVisible()
    assert "not valid YAML" in window.banner.text()
    assert window.rule_list.topLevelItemCount() == 0
    assert _codes(window) == ["HL000"]


def test_missing_rules_file(qtbot, open_window, tmp_path):
    window = open_window(tmp_path / "rules.yaml", _fake(), start=False)
    assert "No rules file" in window.banner.text()
    assert window.rule_list.topLevelItemCount() == 0
    assert _codes(window) == []
    assert window.save_action.isEnabled()  # saving creates the file


def test_cli_without_command_opens_the_gui(monkeypatch, tmp_path):
    from heliostat.ui import app

    calls = []
    monkeypatch.setattr(app, "run", lambda path, client: calls.append((path, client)) or 0)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert cli.main([]) == 0
    assert cli.main(["--rules", "other.yaml"]) == 0
    assert [path for path, _ in calls] == [tmp_path / "solaar" / "rules.yaml", Path("other.yaml")]
