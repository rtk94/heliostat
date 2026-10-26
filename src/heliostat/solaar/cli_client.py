# SPDX-License-Identifier: GPL-2.0-or-later
"""SolaarClient backed by the `solaar` command-line tool."""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable, Sequence

from heliostat.solaar.client import (
    SETTABLE_MODES,
    Control,
    Device,
    DeviceNotFound,
    DivertMode,
    ReloadResult,
    ReloadStrategy,
    SolaarCommandError,
    SolaarError,
)
from heliostat.solaar.parsers import (
    DIVERT_SETTING,
    ShowDevice,
    ShowOutput,
    controls_from_show,
    parse_divert_keys,
    parse_set_divert,
    parse_show,
    parse_version,
)
from heliostat.solaar.reload import RealSystem, System, reload_rules

VERSION_TIMEOUT = 15.0
SHOW_TIMEOUT = 60.0  # `show` pings and reads every feature of every device
CONFIG_TIMEOUT = 30.0

# (argv, timeout, env) -> completed process. Replaced in tests; the default runs the real binary.
Runner = Callable[[Sequence[str], float, dict[str, str]], subprocess.CompletedProcess]


def _run_subprocess(argv, timeout, env):
    return subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def solaar_env() -> dict[str, str]:
    """Heliostat's environment with Solaar's translations off: the parsers read the English labels."""
    env = dict(os.environ)
    env["LC_ALL"] = "C.UTF-8"
    env["LANGUAGE"] = "C"  # gettext checks LANGUAGE before LC_ALL
    return env


class CliSolaarClient:
    """`solaar show` is slow (it pings every device and reads its features), so its output is read at most
    once between refresh() calls and shared by devices() and controls(). A failed `show` is not kept."""

    def __init__(
        self,
        solaar: str = "solaar",
        reload_strategy: ReloadStrategy = ReloadStrategy.RESTART,
        runner: Runner | None = None,
        system: System | None = None,
    ):
        self.solaar = solaar
        self.reload_strategy = reload_strategy
        self.runner = runner
        self.system = system if system is not None else RealSystem()
        self._show: tuple[str, ShowOutput] | None = None
        self._show_lock = threading.Lock()

    def _run(self, *args: str, timeout: float) -> str:
        argv = (self.solaar, *args)
        try:
            done = (self.runner or _run_subprocess)(argv, timeout, solaar_env())
        except subprocess.TimeoutExpired as e:
            raise SolaarCommandError(f"timed out after {timeout} s", argv) from e
        except OSError as e:
            raise SolaarCommandError(f"could not run solaar ({e})", argv) from e
        if done.returncode != 0:
            raise SolaarCommandError(f"exited with status {done.returncode}", argv, done.returncode, done.stderr)
        return done.stdout

    def version(self) -> tuple[int, int, int]:
        return parse_version(self._run("--version", timeout=VERSION_TIMEOUT))

    def is_running(self) -> bool:
        return bool(self.system.solaar_processes())

    def _show_output(self) -> tuple[str, ShowOutput]:
        # Always `show` all devices: `solaar show <serial>` prints the first pairing with that serial,
        # which can be a stale offline pairing on another receiver.
        with self._show_lock:
            if self._show is None:
                raw = self._run("show", timeout=SHOW_TIMEOUT)
                self._show = (raw, parse_show(raw))
            return self._show

    def refresh(self) -> None:
        with self._show_lock:
            self._show = None

    def devices(self) -> list[Device]:
        return [entry.device for entry in self._show_output()[1].devices]

    def controls(self, device: Device) -> list[Control]:
        raw, show = self._show_output()
        return controls_from_show(_online_entry(show.devices, device), raw)

    def set_divert(self, device: Device, control: str, mode: DivertMode) -> None:
        """Set one control's divert-keys mode, then read it back.

        Solaar's `config` writes the device and, if the Solaar GUI is running, forwards the change to it
        so it applies and saves it too. The readback can only confirm the divert bit: Mouse Gestures and
        Sliding DPI read back as Diverted.
        """
        if mode not in SETTABLE_MODES:
            raise ValueError(f"{mode} cannot be set")
        target = _cli_device_arg(device)
        try:
            self._set_divert(target, control, mode)
        finally:
            self.refresh()  # whether or not it worked, the device may have changed

    def _set_divert(self, target: str, control: str, mode: DivertMode) -> None:
        out = self._run("config", target, DIVERT_SETTING, control, mode.value, timeout=CONFIG_TIMEOUT)
        _, set_control, set_mode = parse_set_divert(out)
        if set_control != control or set_mode is not mode:
            raise SolaarError(f"Solaar set {set_control!r} to {set_mode.value!r}, asked for {control!r} {mode.value!r}")
        readback = parse_divert_keys(self._run("config", target, DIVERT_SETTING, timeout=CONFIG_TIMEOUT))
        if control not in readback:
            raise SolaarError(f"{control!r} is missing from divert-keys after setting it")
        if readback[control].diverted != mode.diverted:
            raise SolaarError(f"{control!r} reads back as {readback[control].value!r} after setting {mode.value!r}")

    def reload_rules(self) -> ReloadResult:
        try:
            return reload_rules(self.reload_strategy, self.version, self.system)
        finally:
            self.refresh()  # a restarted Solaar applies its saved settings to the devices again


def _cli_device_arg(device: Device) -> str:
    """How to name the device to `solaar config`: by serial (it matches serials exactly and skips offline pairings)."""
    if not device.serial:
        raise DeviceNotFound(f"device {device.name!r} has no serial number to address it by")
    return device.serial


def _online_entry(entries: list[ShowDevice], device: Device) -> ShowDevice:
    matches = [
        e
        for e in entries
        if e.device.online
        and e.device.serial == device.serial
        and (device.unit_id is None or e.device.unit_id == device.unit_id)
    ]
    if not matches:
        raise DeviceNotFound(f"no online device with serial {device.serial!r} ({device.name})")
    if len(matches) > 1:
        raise SolaarError(f"{len(matches)} online devices with serial {device.serial!r}")
    return matches[0]
