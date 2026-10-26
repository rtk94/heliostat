# SPDX-License-Identifier: GPL-2.0-or-later
"""Editing in the GUI: simple form, advanced tree, rule list, undo/redo, save, apply. Headless, with
FakeSolaar and temp files only."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QDialogButtonBox

from heliostat.model import KeyPress, Raw, Rule
from heliostat.rulesfile import BACKUPS_KEPT, backups, dumps, loads
from heliostat.simple import KeyTrigger, SimpleRule, generate
from heliostat.solaar import FakeSolaar, ReloadOutcome, ReloadResult
from heliostat.ui.dialogs import SimpleRuleDialog, parse_component, parse_rule
from heliostat.ui.main_window import COMPONENT_TEMPLATES, PATH_ROLE, MainWindow

SHOW = Path(__file__).parent / "fixtures" / "solaar" / "1.1.14" / "show_all_back-gestures.txt"
ENV = {"XDG_SESSION_TYPE": "x11"}

# In the shapes Solaar's save writes, so that save leaves every unedited line as it is.
RULES = """\
%YAML 1.3
---
- Key: [Back Button, pressed]
- KeyPress:
  - [Control_L, Tab]
  - click
...
---
- Feature: THUMB_WHEEL
- Rule:
  - Test: thumb_wheel_up
  - KeyPress:
    - XF86_AudioRaiseVolume
    - click
...
---
- Key: [Forward Button, pressed]
- Frobnicate:
  - 1
  - a: b
- KeyPress:
  - Alt_L
  - click
...
"""

RULE_1 = RULES.split("...\n")[0].removeprefix("%YAML 1.3\n") + "...\n"
RULE_2 = RULES.split("...\n")[1] + "...\n"
RULE_3 = RULES.split("...\n")[2] + "...\n"


def _fake(cls=FakeSolaar):
    return cls.from_show(SHOW.read_text(), version=(1, 1, 14))


class Asked:
    """Stands in for the window's ask_* methods: records the calls and gives canned answers."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.answers.pop(0)


def _refuse(*args):
    raise AssertionError(f"unexpected question: {args!r}")


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
    def open_window(path, client=None):
        window = MainWindow(path, client or _fake(), pool=pool, env=ENV)
        for name in ("ask_external_change", "ask_discard", "ask_new_rule", "ask_yaml", "show_error"):
            setattr(window, name, _refuse)
        window.ask_unsaved = lambda: "discard"
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        return window

    return open_window


@pytest.fixture
def window(open_window, rules_file):
    return open_window(rules_file)


def _select(window, index, path=None):
    window.rule_list.setCurrentItem(window.rule_list.topLevelItem(index))
    if path is not None:
        window.rule_tree.setCurrentItem(window._tree_items[path])


def _rule_texts(window):
    return [window.rule_list.topLevelItem(i).text(1) for i in range(window.rule_list.topLevelItemCount())]


def _type(qtbot, line_edit, text):
    line_edit.selectAll()
    qtbot.keyClick(line_edit, Qt.Key.Key_Backspace)
    qtbot.keyClicks(line_edit, text)


def test_simple_edits_then_save(qtbot, window, rules_file):
    _select(window, 0)
    editor = window.simple_editor
    assert window.editor_tabs.currentIndex() == window.simple_tab
    assert editor.preview.text() == "When Back Button is pressed: press Ctrl+Tab"

    editor.trigger_kind.setCurrentIndex(editor.trigger_kind.findData("released"))
    editor.process_box.setChecked(True)
    qtbot.keyClicks(editor.process, "firefox")
    editor.action_list.setCurrentRow(0)
    _type(qtbot, editor.action_editor.keys, "Control_L Shift_L Tab")
    assert editor.preview.text() == "When Back Button is released in firefox: press Ctrl+Shift+Tab"
    assert _rule_texts(window)[0] == editor.preview.text()
    assert window.isWindowModified()

    assert window.save()
    assert rules_file.read_text() == RULES.replace(
        "- Key: [Back Button, pressed]\n- KeyPress:\n  - [Control_L, Tab]\n",
        "- Key: [Back Button, released]\n- Process: firefox\n- KeyPress:\n  - [Control_L, Shift_L, Tab]\n",
    )
    assert not window.isWindowModified()
    assert window.save_result.text().startswith(f"Saved {rules_file}; backup rules.yaml.heliostat-bak.")
    (backup,) = backups(rules_file)
    assert backup.read_text() == RULES


def test_simple_edit_keeps_untouched_fields_as_loaded(qtbot, open_window, tmp_path):
    """A Device argument that is an online device's name (which Solaar 1.1.20 matches, 1.1.14 does not)
    must not turn into that device's serial when another field is edited."""
    path = tmp_path / "rules.yaml"
    text = "%YAML 1.3\n---\n- Device: Signature M650 Mouse\n- Key: Back Button\n- KeyPress: a\n...\n"
    path.write_text(text)
    window = open_window(path)
    with qtbot.waitSignal(window.solaarLoaded, timeout=10_000):
        window.start_solaar()
    _select(window, 0)
    editor = window.simple_editor
    assert editor.device.currentText() == "Signature M650 Mouse"
    assert "Back Button" in [editor.key.itemText(i) for i in range(editor.key.count())]
    editor.process_box.setChecked(True)
    qtbot.keyClicks(editor.process, "kitty")
    assert window.save()
    assert path.read_text() == text.replace("- KeyPress: a\n", "- Process: kitty\n- KeyPress: a\n")
    editor.device.setCurrentIndex(1)  # the online device: written by serial
    assert window.save()
    assert "- Device: Signature M650 Mouse\n" not in path.read_text()


def test_simple_actions_add_remove_reorder(qtbot, window, rules_file):
    _select(window, 0)
    editor = window.simple_editor
    assert not editor.remove_action.isEnabled()  # the last action stays: a simple rule needs one
    editor.append_action(KeyPress(["a"], "click"))
    editor.action_list.setCurrentRow(1)
    editor.action_up.click()
    assert _rule_texts(window)[0] == "When Back Button is pressed: press A, then press Ctrl+Tab"
    editor.action_list.setCurrentRow(1)
    editor.remove_action.click()
    assert window.save()
    assert rules_file.read_text() == RULES.replace(
        "- KeyPress:\n  - [Control_L, Tab]\n  - click\n", "- KeyPress:\n  - a\n  - click\n", 1
    )


def test_undo_redo(qtbot, window):
    stack = window.document.undo_stack
    _select(window, 0)
    editor = window.simple_editor
    editor.process_box.setChecked(True)
    qtbot.keyClicks(editor.process, "firefox")
    assert stack.count() == 2  # checking the box, then the typing as one step
    stack.undo()
    assert editor.process.text() == "" and editor.process_box.isChecked()
    assert dumps(window.document.ruleset).count("- Process: ''\n") == 1
    stack.undo()
    assert not editor.process_box.isChecked()
    assert dumps(window.document.ruleset) == RULES
    assert not window.isWindowModified()
    stack.redo()
    stack.redo()
    assert editor.process.text() == "firefox"
    assert _rule_texts(window)[0] == "When Back Button is pressed in firefox: press Ctrl+Tab"

    _select(window, 2)
    window.move_rule(-1)
    window.delete_rule()
    window.duplicate_rule()
    assert len(window.rules) == 3
    for _ in range(3):
        stack.undo()
    assert window.current_index() == 2
    stack.undo()
    stack.undo()
    assert dumps(window.document.ruleset) == RULES
    assert not window.isWindowModified()
    assert window.undo_action.isEnabled() is False


def test_save_after_undo_to_clean_writes_nothing_new(window, rules_file):
    _select(window, 0)
    window.delete_rule()
    window.document.undo_stack.undo()
    assert window.save()
    assert window.save_result.text() == "No changes to save"
    assert backups(rules_file) == []


def test_raw_survives_sibling_edit(window, rules_file):
    _select(window, 2, (2, 0))
    window.ask_yaml = lambda title, text, parse: parse("Key: [Forward Button, released]")[0]
    window.edit_component()
    _select(window, 2, (2, 2))
    window.remove_component()
    window.ask_yaml = lambda title, text, parse: parse(text)[0]
    window.add_component(COMPONENT_TEMPLATES["Actions"]["MouseClick"], inside=False)
    assert window.save()
    expected_rule = (
        "---\n- Key: [Forward Button, released]\n- Frobnicate:\n  - 1\n  - a: b\n- MouseClick: [left, 1]\n...\n"
    )
    assert rules_file.read_text() == RULES.replace(RULE_3, expected_rule)
    assert isinstance(window.rules[2].components[1], Raw)


def test_edit_raw_as_yaml(window, rules_file):
    _select(window, 2, (2, 1))
    seen = []

    def ask(title, text, parse):
        seen.append(text)
        return parse("Frobnicate: [2]")[0]

    window.ask_yaml = ask
    window.edit_component()
    assert seen == ["Frobnicate:\n- 1\n- a: b\n"]
    assert window.save()
    assert "- Frobnicate: [2]\n" in rules_file.read_text()


def test_tree_add_inside_and_move(window, rules_file):
    _select(window, 1, (1, 1))
    window.ask_yaml = lambda title, text, parse: parse("Test: thumb_wheel_down")[0]
    window.add_component("Test: x", inside=True)
    assert window.current_component_path() == (1, 1, 2)
    window.move_component(-1)
    window.move_component(-1)
    assert window.current_component_path() == (1, 1, 0)
    assert window.save()
    assert "- Rule:\n  - Test: thumb_wheel_down\n  - Test: thumb_wheel_up\n" in rules_file.read_text()


def test_rule_yaml_edit_and_new_rules(window, rules_file):
    _select(window, 1)
    window.ask_yaml = lambda title, text, parse: parse(text.replace("thumb_wheel_up", "thumb_wheel_down"))[0]
    window.edit_rule_yaml()
    new = generate(SimpleRule(KeyTrigger("Smart Shift"), [KeyPress(["XF86_AudioMute"], "click")]))
    window.ask_new_rule = lambda: new
    window.new_simple_rule()
    assert window.current_index() == 2
    window.new_advanced_rule()
    assert window.current_index() == 3 and window.editor_tabs.currentIndex() == window.advanced_tab
    assert window.save()
    text = rules_file.read_text()
    assert text == (
        RULES.replace("thumb_wheel_up", "thumb_wheel_down").replace(
            RULE_3,
            "---\n- Key: [Smart Shift, pressed]\n- KeyPress:\n  - XF86_AudioMute\n  - click\n...\n--- []\n...\n"
            + RULE_3,
        )
    )


def test_external_change_cancel_then_overwrite(window, rules_file):
    external = RULES + "---\n- Process: kwin\n...\n"
    rules_file.write_text(external)
    _select(window, 0)
    window.delete_rule()
    window.ask_external_change = asked = Asked("cancel")
    assert not window.save()
    assert rules_file.read_text() == external
    assert window.isWindowModified()
    (change,) = asked.calls[0]
    assert "+- Process: kwin\n" in change.diff()

    window.ask_external_change = Asked("overwrite")
    assert window.save()
    assert rules_file.read_text() == dumps(window.document.ruleset) == RULES.replace(RULE_1, "")
    (backup,) = backups(rules_file)
    assert backup.read_text() == external
    assert not window.isWindowModified()


def test_external_change_reload(window, rules_file):
    external = RULES.replace(RULE_2, "")
    rules_file.write_text(external)
    _select(window, 0)
    window.duplicate_rule()
    window.ask_external_change = Asked("reload")
    assert not window.save()
    assert rules_file.read_text() == external
    assert dumps(window.document.ruleset) == external
    assert window.document.undo_stack.count() == 0 and not window.isWindowModified()
    assert len(_rule_texts(window)) == 2


def test_file_deleted_on_disk(window, rules_file):
    rules_file.unlink()
    window.ask_external_change = asked = Asked("cancel")
    assert not window.save()
    assert "was deleted" in str(asked.calls[0][0])
    assert not rules_file.exists()


def test_backups_rotate_at_ten(window, rules_file):
    _select(window, 0)
    for _ in range(BACKUPS_KEPT + 2):
        window.duplicate_rule()
        assert window.save()
    kept = backups(rules_file)
    assert len(kept) == BACKUPS_KEPT
    assert len(loads(kept[0].read_bytes()).rules) == 5  # the two oldest (3 and 4 rules) are gone
    assert len(loads(kept[-1].read_bytes()).rules) == 3 + BACKUPS_KEPT + 1


def test_missing_file_is_created(open_window, tmp_path):
    path = tmp_path / "solaar" / "rules.yaml"
    window = open_window(path)
    window.ask_new_rule = lambda: generate(SimpleRule(KeyTrigger("Back Button"), [KeyPress(["a"], "click")]))
    window.new_simple_rule()
    assert window.save()
    assert path.read_text() == "%YAML 1.3\n---\n- Key: [Back Button, pressed]\n- KeyPress:\n  - a\n  - click\n...\n"
    assert not window.banner.isVisible()


def test_broken_yaml_is_read_only(open_window, tmp_path):
    path = tmp_path / "rules.yaml"
    text = "---\n- Key: [A, pressed]\n...\n---\n- Key: [B\n"
    path.write_text(text)
    window = open_window(path)
    assert not window.save_action.isEnabled()
    assert not window.apply_action.isEnabled()
    assert not window.new_rule_action.isEnabled()
    assert not window.simple_editor.isEnabled()
    assert not window.save()
    window.apply()
    assert path.read_text() == text and window.client.reload_calls == 0


def test_problems_rerun_after_edits(qtbot, window):
    assert not any(p.rule_path[:1] == (3,) for p in window.problems)
    window.ask_new_rule = lambda: generate(SimpleRule(KeyTrigger("No Such Control"), [KeyPress(["a"], "click")]))
    with qtbot.waitSignal(window.problemsUpdated, timeout=5_000):
        window.new_simple_rule()
        assert not any(p.rule_path[:1] == (3,) for p in window.problems)  # not yet: lint waits for edits to stop
    assert any(p.code == "HL002" and p.rule_path[:1] == (3,) for p in window.problems)
    assert window.statusBar().currentMessage().startswith("4 rules")


def test_apply_saves_and_reloads(qtbot, window, rules_file):
    _select(window, 0)
    window.delete_rule()
    with qtbot.waitSignal(window.applied, timeout=10_000) as blocker:
        window.apply()
    result = blocker.args[0]
    assert result.outcome is ReloadOutcome.RESTARTED
    assert window.client.reload_calls == 1
    assert rules_file.read_text() == RULES.replace(RULE_1, "")
    assert window.save_result.text() == "Applied: restarted (fake)"
    assert "outcome:  restarted" in window.save_result.toolTip()


class FailingReload(FakeSolaar):
    def reload_rules(self):
        self.reload_calls += 1
        return ReloadResult(ReloadOutcome.FAILED, self.reload_strategy, "systemctl failed (fake)")


def test_apply_reports_a_failed_reload(qtbot, open_window, rules_file):
    window = open_window(rules_file, _fake(FailingReload))
    window.show_error = errors = Asked(None)
    with qtbot.waitSignal(window.applied, timeout=10_000):
        window.apply()
    assert window.save_result.text() == "Saved, but Solaar has not loaded the rules: systemctl failed (fake)"
    assert errors.calls[0][0] == "Solaar did not load the rules"


def test_apply_stops_when_save_is_refused(window, rules_file):
    rules_file.write_text(RULES + "---\n- Process: kwin\n...\n")
    window.ask_external_change = Asked("cancel")
    window.apply()
    assert window.client.reload_calls == 0


def test_close_with_unsaved_changes(window, rules_file):
    _select(window, 0)
    window.delete_rule()
    window.ask_unsaved = Asked("cancel")
    window.close()
    assert window.isVisible()
    window.ask_unsaved = Asked("save")
    window.close()
    assert not window.isVisible()
    assert rules_file.read_text() == RULES.replace(RULE_1, "")


def test_simple_tab_follows_the_rule(window):
    _select(window, 1)
    assert not window.editor_tabs.isTabEnabled(window.simple_tab)
    assert window.editor_tabs.currentIndex() == window.advanced_tab
    _select(window, 0, (0, 0))
    assert window.editor_tabs.isTabEnabled(window.simple_tab)
    window.ask_yaml = lambda title, text, parse: parse("Or: []")[0]
    window.edit_component()  # no longer a simple rule
    assert not window.editor_tabs.isTabEnabled(window.simple_tab)
    assert window.rule_heading.text() == "Rule 1: advanced (Or condition)"
    window.document.undo_stack.undo()
    assert window.editor_tabs.isTabEnabled(window.simple_tab)
    assert window.rule_tree.currentItem().data(0, PATH_ROLE) == (0, 0)


def test_component_templates_cover_every_type():
    from heliostat.model import COMPONENT_TYPES

    names = [name for group in COMPONENT_TEMPLATES.values() for name in group]
    assert sorted(names) == sorted(COMPONENT_TYPES)
    for group in COMPONENT_TEMPLATES.values():
        for name, template in group.items():
            component, _note = parse_component(template)
            assert component.TYPE == name


def test_parse_rule_and_component_notes():
    rule, note = parse_rule("- Key: [A, pressed]\n- Foo: 1\n")
    assert isinstance(rule, Rule) and "1 not recognized" in note
    raw, note = parse_rule("just text")
    assert isinstance(raw, Raw) and "Solaar cannot load" in note
    with pytest.raises(ValueError):
        parse_component("Key: [A")
    with pytest.raises(ValueError):
        parse_component("---\na: 1\n---\nb: 2\n")


def test_new_rule_dialog(qtbot):
    controls = [("Back Button", "Diverted"), ("Forward Button", "Regular")]
    dialog = SimpleRuleDialog(None, [("Signature M650 Mouse", "4A3B12CD", controls)], {"4A3B12CD": "M650"})
    qtbot.addWidget(dialog)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    editor = dialog.editor
    assert not ok.isEnabled()
    assert [editor.key.itemText(i) for i in range(editor.key.count())] == ["Back Button", "Forward Button"]
    editor.device.setCurrentIndex(1)
    editor.key.setCurrentIndex(0)
    assert not ok.isEnabled() and editor.message.text() == "Add an action."
    editor.append_action(KeyPress(["Control_L", "c"], "click"))
    assert ok.isEnabled()
    assert editor.preview.text() == "When Back Button on M650 is pressed: press Ctrl+C"
    ok.click()
    assert dumps(loads(dumps_rule(dialog.rule))) == dumps_rule(dialog.rule)
    assert dumps_rule(dialog.rule) == (
        "%YAML 1.3\n---\n- Key: [Back Button, pressed]\n- Device: 4A3B12CD\n- KeyPress:\n"
        "  - [Control_L, c]\n  - click\n...\n"
    )


def dumps_rule(rule):
    from heliostat.model import RuleSet

    return dumps(RuleSet([rule]))
