# SPDX-License-Identifier: GPL-2.0-or-later
"""In-memory SolaarClient for tests. Mirrors what the real CLI can and cannot observe."""

from __future__ import annotations

from dataclasses import replace

from heliostat.solaar.client import (
    SETTABLE_MODES,
    Control,
    Device,
    DeviceNotFound,
    DivertMode,
    ReloadOutcome,
    ReloadResult,
    ReloadStrategy,
    SolaarCommandError,
)
from heliostat.solaar.parsers import controls_from_show, parse_show


class FakeSolaar:
    """A configurable Solaar.

    `controls` maps a device serial to its controls. set_divert() behaves like the real CLI: a control
    that offers Mouse Gestures reads back as DIVERTED_MODE_UNKNOWN for any non-Regular mode, and the
    mode set is recorded as its saved_mode. Calls are recorded in `divert_calls` and `reload_calls`.
    """

    def __init__(
        self,
        devices: list[Device] | None = None,
        controls: dict[str, list[Control]] | None = None,
        version: tuple[int, int, int] = (1, 1, 14),
        running: bool = True,
        reload_strategy: ReloadStrategy = ReloadStrategy.RESTART,
    ):
        self._devices = list(devices or [])
        self._controls = {serial: list(cs) for serial, cs in (controls or {}).items()}
        self._version = version
        self.running = running
        self.reload_strategy = reload_strategy
        self.divert_calls: list[tuple[str | None, str, DivertMode]] = []
        self.reload_calls = 0

    @classmethod
    def from_show(cls, text: str, **kwargs) -> FakeSolaar:
        """Build from captured `solaar show` output (e.g. a fixture file)."""
        entries = parse_show(text).devices
        controls = {e.device.serial: controls_from_show(e, text) for e in entries if e.device.online}
        return cls(devices=[e.device for e in entries], controls=controls, **kwargs)

    def version(self) -> tuple[int, int, int]:
        return self._version

    def is_running(self) -> bool:
        return self.running

    def devices(self) -> list[Device]:
        return list(self._devices)

    def _online(self, device: Device) -> Device:
        for d in self._devices:
            if d.online and d.serial == device.serial and (device.unit_id is None or d.unit_id == device.unit_id):
                return d
        raise DeviceNotFound(f"no online device with serial {device.serial!r} ({device.name})")

    def controls(self, device: Device) -> list[Control]:
        return list(self._controls.get(self._online(device).serial, []))

    def set_divert(self, device: Device, control: str, mode: DivertMode) -> None:
        if mode not in SETTABLE_MODES:
            raise ValueError(f"{mode} cannot be set")
        serial = self._online(device).serial
        argv = ("solaar", "config", str(serial), "divert-keys", control, mode.value)
        controls = self._controls.get(serial, [])
        i = next((i for i, c in enumerate(controls) if c.name == control), None)
        if i is None:
            raise SolaarCommandError("exited with status 1", argv, 1, f"divert-keys: key '{control}' not in setting")
        c = controls[i]
        if not c.divertable or mode not in c.modes:
            raise SolaarCommandError("exited with status 1", argv, 1, f"divert-keys: possible values are {c.modes}")
        live = mode
        if mode.diverted and DivertMode.MOUSE_GESTURES in c.modes:
            live = DivertMode.DIVERTED_MODE_UNKNOWN
        controls[i] = replace(c, mode=live, saved_mode=mode)
        self.divert_calls.append((serial, control, mode))

    def reload_rules(self) -> ReloadResult:
        self.reload_calls += 1
        if not self.running:
            return ReloadResult(ReloadOutcome.NOT_RUNNING, self.reload_strategy, "Solaar is not running (fake)")
        if self.reload_strategy is ReloadStrategy.REMOTE:
            return ReloadResult(ReloadOutcome.UNSUPPORTED, self.reload_strategy, "no remote reload (fake)")
        return ReloadResult(ReloadOutcome.RESTARTED, self.reload_strategy, "restarted (fake)", method="fake")
