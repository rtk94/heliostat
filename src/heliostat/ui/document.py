# SPDX-License-Identifier: GPL-2.0-or-later
"""The rules being edited, with undo and redo.

Every edit replaces the whole RuleSet with a new one (built by `model.edit` or by generating a simple
rule), through a QUndoCommand that holds the RuleSet before and after. Rules files are small, so
whole snapshots keep each command trivially correct, whatever the edit was.

Edits that carry a `merge_key` merge with the command before them when it has the same key, so typing
a name into a field is one undo step, not one per keystroke.
"""

from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from heliostat.model import RuleSet
from heliostat.rulesfile import dumps

RulePath = tuple[int, ...]

_MERGE_ID = 1


class _Edit(QUndoCommand):
    def __init__(
        self,
        document: RulesDocument,
        label: str,
        before: RuleSet,
        after: RuleSet,
        select_before: RulePath | None,
        select_after: RulePath | None,
        merge_key: Any,
        source: Any,
    ):
        super().__init__(label)
        self.document = document
        self.before = before
        self.after = after
        self.select_before = select_before
        self.select_after = select_after
        self.merge_key = merge_key
        self.source = source
        self._first = True

    def id(self) -> int:
        return _MERGE_ID if self.merge_key is not None else -1

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, _Edit) or other.merge_key != self.merge_key:
            return False
        stack = self.document.undo_stack
        if stack.cleanIndex() == stack.index():
            return False  # this command is the saved state; keep it reachable by undo
        self.after = other.after
        self.select_after = other.select_after
        self.setObsolete(_same(self.after, self.before))
        return True

    def redo(self) -> None:
        # The first redo is QUndoStack.push(); the change comes from `source`, which already shows it.
        source = self.source if self._first else None
        self._first = False
        self.document._set(self.after, self.select_after, source)

    def undo(self) -> None:
        self.document._set(self.before, self.select_before, None)


class RulesDocument(QObject):
    """Emits changed(select, source) after the rules change: `select` is the rule path to select (or
    None to keep the selection), `source` is whoever made the edit (None for undo, redo and reset), so
    a form that made an edit need not reload itself."""

    changed = Signal(object, object)

    def __init__(self, ruleset: RuleSet, parent: QObject | None = None):
        super().__init__(parent)
        self._ruleset = ruleset
        self.undo_stack = QUndoStack(self)

    @property
    def ruleset(self) -> RuleSet:
        return self._ruleset

    def edit(
        self,
        label: str,
        after: RuleSet,
        select: RulePath | None = None,
        *,
        select_before: RulePath | None = None,
        merge_key: Any = None,
        source: Any = None,
    ) -> bool:
        """Replace the rules with `after` as one undo step. Returns False (and does nothing) if nothing changed."""
        if _same(after, self._ruleset):
            return False
        command = _Edit(self, label, self._ruleset, after, select_before, select, merge_key, source)
        self.undo_stack.push(command)
        return True

    def reset(self, ruleset: RuleSet) -> None:
        """Start over with `ruleset` (after reloading the file): no undo history, clean."""
        self.undo_stack.clear()
        self._set(ruleset, None, None)
        self.undo_stack.setClean()

    def _set(self, ruleset: RuleSet, select: RulePath | None, source: Any) -> None:
        self._ruleset = copy.deepcopy(ruleset)
        self.changed.emit(select, source)


def _same(a: RuleSet, b: RuleSet) -> bool:
    """Written the same. Not `==`: a loaded `Device: 1` equals `Device: true` in Python."""
    return dumps(a) == dumps(b)
