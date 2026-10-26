# SPDX-License-Identifier: GPL-2.0-or-later
"""The one seam between Heliostat and Solaar: the SolaarClient protocol and the data it returns."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class SolaarError(Exception):
    """Something went wrong talking to Solaar."""


class SolaarOutputError(SolaarError):
    """Solaar printed something the parsers do not recognize. `raw` is the full text that was being parsed."""

    def __init__(self, message: str, raw: str, line: int | None = None):
        self.raw = raw
        self.line = line
        where = f" (line {line})" if line is not None else ""
        super().__init__(f"unrecognized Solaar output{where}: {message}\n--- raw output ---\n{raw}")


class SolaarCommandError(SolaarError):
    """A `solaar` command failed to run, timed out, or exited non-zero."""

    def __init__(self, message: str, argv: tuple[str, ...], returncode: int | None = None, stderr: str = ""):
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr
        detail = f"\n--- stderr ---\n{stderr}" if stderr else ""
        super().__init__(f"{message}: {' '.join(argv)}{detail}")


class DeviceNotFound(SolaarError):
    """No online device matches the one asked for."""


class DivertMode(enum.Enum):
    """A control's `divert-keys` value. Values are Solaar's own labels (as printed by its CLI)."""

    REGULAR = "Regular"
    DIVERTED = "Diverted"
    MOUSE_GESTURES = "Mouse Gestures"
    SLIDING_DPI = "Sliding DPI"
    # Solaar reads `divert-keys` from the device's divert bit alone (DivertKeys.rw_class.read), so a
    # control in Mouse Gestures or Sliding DPI mode reads back as Diverted. For a control that offers
    # those modes, a live "Diverted" therefore cannot tell the three apart.
    DIVERTED_MODE_UNKNOWN = "diverted (gesture mode unknown)"

    @property
    def diverted(self) -> bool:
        """True if the control sends HID++ notifications, so rules can see it."""
        return self is not DivertMode.REGULAR


# The modes `solaar config <device> divert-keys <control> <mode>` accepts. DIVERTED_MODE_UNKNOWN is read-only.
SETTABLE_MODES = (DivertMode.REGULAR, DivertMode.DIVERTED, DivertMode.MOUSE_GESTURES, DivertMode.SLIDING_DPI)


@dataclass(frozen=True)
class Device:
    """One device entry from `solaar show`. An offline pairing has no unit ID and Solaar shows its codename as name."""

    name: str
    codename: str | None
    serial: str | None
    unit_id: str | None
    kind: str | None
    online: bool


@dataclass(frozen=True)
class Control:
    """A reprogrammable control (key or button) of a device.

    `name` is the Logitech control name Solaar uses, the same one a rule's Key condition names.
    `divertable` means Solaar's `divert-keys` setting covers it (divertable and not virtual).
    `mode` is the live diversion read from the device (None if not divertable or the read failed);
    `saved_mode` is what Solaar has stored for it in its config.yaml, if anything. `modes` are the
    modes Solaar offers for this control.
    """

    name: str
    divertable: bool
    mode: DivertMode | None
    modes: tuple[DivertMode, ...] = ()
    saved_mode: DivertMode | None = None
    flags: tuple[str, ...] = ()


class ReloadStrategy(enum.Enum):
    AUTO = "auto"
    REMOTE = "remote"
    RESTART = "restart"


class ReloadOutcome(enum.Enum):
    RESTARTED = "restarted"
    RELOADED = "reloaded"  # by the remote command (not available in any Solaar release yet)
    NOT_RUNNING = "not running"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


@dataclass(frozen=True)
class ReloadResult:
    """What reload_rules() did, step by step. `steps` is a human-readable log of every action and observation."""

    outcome: ReloadOutcome
    strategy: ReloadStrategy
    message: str
    method: str | None = None  # "systemd" (systemctl --user restart) or "signal" (SIGTERM + relaunch)
    unit: str | None = None
    old_pid: int | None = None
    new_pid: int | None = None
    argv: tuple[str, ...] | None = None
    steps: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """True if Solaar is now running the rules file as saved (or is not running and will read it at start)."""
        return self.outcome in (ReloadOutcome.RESTARTED, ReloadOutcome.RELOADED, ReloadOutcome.NOT_RUNNING)

    def __str__(self) -> str:
        lines = [
            f"outcome:  {self.outcome.value}",
            f"strategy: {self.strategy.value}",
            f"method:   {self.method or '-'}",
            f"unit:     {self.unit or '-'}",
            f"old pid:  {self.old_pid if self.old_pid is not None else '-'}",
            f"new pid:  {self.new_pid if self.new_pid is not None else '-'}",
            f"argv:     {' '.join(self.argv) if self.argv else '-'}",
            f"message:  {self.message}",
            "steps:",
        ]
        lines += [f"  {i}. {step}" for i, step in enumerate(self.steps, 1)]
        return "\n".join(lines)


@runtime_checkable
class SolaarClient(Protocol):
    def version(self) -> tuple[int, int, int]: ...

    def is_running(self) -> bool:
        """True if the Solaar GUI/tray process (the one that runs rules) is running for this user."""
        ...

    def devices(self) -> list[Device]: ...

    def controls(self, device: Device) -> list[Control]: ...

    def refresh(self) -> None:
        """Forget device data read so far, so the next devices() / controls() reads Solaar again.

        A client may keep what it read between calls; call this before reading Solaar state anew.
        set_divert() and reload_rules() do it themselves.
        """
        ...

    def set_divert(self, device: Device, control: str, mode: DivertMode) -> None: ...

    def reload_rules(self) -> ReloadResult: ...
