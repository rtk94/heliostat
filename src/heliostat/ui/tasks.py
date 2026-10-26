# SPDX-License-Identifier: GPL-2.0-or-later
"""Run slow work (the `solaar` CLI) on a thread pool and get its results back on the GUI thread."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal


class TaskSignals(QObject):
    """Lives on the GUI thread, so slots connected to it run there (queued from the worker)."""

    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    """Runs `work(report)` on a pool thread. `report(x)` emits progress(x); the return value is emitted
    by finished, an exception's traceback by failed. Create it on the GUI thread."""

    def __init__(self, work: Callable[[Callable[[Any], None]], Any]):
        super().__init__()
        self.work = work
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            result = self.work(self.signals.progress.emit)
        except Exception:
            self.signals.failed.emit(traceback.format_exc())
        else:
            self.signals.finished.emit(result)
