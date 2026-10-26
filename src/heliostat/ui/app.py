# SPDX-License-Identifier: GPL-2.0-or-later
"""Start the GUI."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from heliostat.solaar import SolaarClient
from heliostat.ui.main_window import MainWindow

APP_ID = "io.github.rtk94.Heliostat"


def run(rules_path: Path, client: SolaarClient) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Heliostat")
    app.setDesktopFileName(APP_ID)
    window = MainWindow(rules_path, client)
    window.show()
    window.start_solaar()
    return app.exec()
