# SPDX-License-Identifier: GPL-2.0-or-later
"""Guards: no automated test may run the real `solaar`, signal a process, spawn one, or call systemctl."""

import os

import pytest

from heliostat.solaar import cli_client, reload

# GUI tests run headless unless a platform is chosen explicitly.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _forbidden(*args, **kwargs):
    raise AssertionError(f"a test reached the real system: {args!r}")


@pytest.fixture(autouse=True)
def _no_real_solaar(monkeypatch):
    monkeypatch.setattr(cli_client, "_run_subprocess", _forbidden)
    monkeypatch.setattr(reload.RealSystem, "terminate", _forbidden)
    monkeypatch.setattr(reload.RealSystem, "spawn", _forbidden)
    monkeypatch.setattr(reload.RealSystem, "systemctl", _forbidden)
