# SPDX-License-Identifier: GPL-2.0-or-later
"""Everything Heliostat learns from or asks of Solaar goes through a SolaarClient."""

from heliostat.solaar.cli_client import CliSolaarClient
from heliostat.solaar.client import (
    SETTABLE_MODES,
    Control,
    Device,
    DeviceNotFound,
    DivertMode,
    ReloadOutcome,
    ReloadResult,
    ReloadStrategy,
    SolaarClient,
    SolaarCommandError,
    SolaarError,
    SolaarOutputError,
)
from heliostat.solaar.fake import FakeSolaar
from heliostat.solaar.reload import REMOTE_RELOAD_MIN_VERSION

__all__ = [
    "REMOTE_RELOAD_MIN_VERSION",
    "SETTABLE_MODES",
    "CliSolaarClient",
    "Control",
    "Device",
    "DeviceNotFound",
    "DivertMode",
    "FakeSolaar",
    "ReloadOutcome",
    "ReloadResult",
    "ReloadStrategy",
    "SolaarClient",
    "SolaarCommandError",
    "SolaarError",
    "SolaarOutputError",
]
