# SPDX-License-Identifier: GPL-2.0-or-later
"""Read what the GUI shows about Solaar, in steps, off the GUI thread. No Qt here.

`read_solaar` refreshes the client, so device data is read anew, then asks it for the version and
whether Solaar is running, then the devices, then their controls, and reports a SolaarState after each
step so the sidebar fills in as answers arrive. The lint context is built by `LintContext.from_client`
(the same as `heliostat lint`) on a wrapper that remembers every answer and error, so no question is
asked twice: one `solaar --version` and, with CliSolaarClient, one `solaar show` per read.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from heliostat.analysis import LintContext
from heliostat.solaar import Control, Device, SolaarClient, SolaarCommandError, SolaarError


@dataclass(frozen=True)
class SolaarState:
    """What is known so far. `done` is False while later steps are still running.

    `version_error`, `devices_error` and `controls_error` say why the version, the device list or the
    controls could not be read, `solaar_missing` that the `solaar` command could not be run at all.
    `controls` maps each online device to its controls (empty if they could not be read); `context` is
    the lint context, set when `done`.
    """

    done: bool = False
    version: tuple[int, int, int] | None = None
    version_error: str | None = None
    solaar_missing: bool = False
    running: bool | None = None
    devices: tuple[Device, ...] | None = None
    devices_error: str | None = None
    controls_error: str | None = None
    controls: dict[Device, tuple[Control, ...]] = field(default_factory=dict)
    context: LintContext | None = None

    @property
    def device_names(self) -> dict[Any, str]:
        """Device condition arguments a rule can use for each online device (unit ID, serial), to its name."""
        names: dict[Any, str] = {}
        for d in self.devices or ():
            if d.online:
                for key in (d.serial, d.unit_id):
                    if key is not None:
                        names.setdefault(key, d.name)
        return names


class _Remembering:
    """A SolaarClient that asks the real one each question once, and replays answers and errors."""

    def __init__(self, client: SolaarClient):
        self._client = client
        self._answers: dict[tuple, tuple[bool, Any]] = {}

    def _ask(self, key: tuple, call: Callable[[], Any]) -> Any:
        if key not in self._answers:
            try:
                self._answers[key] = (True, call())
            except SolaarError as e:
                self._answers[key] = (False, e)
        ok, answer = self._answers[key]
        if not ok:
            raise answer
        return answer

    def version(self):
        return self._ask(("version",), self._client.version)

    def is_running(self):
        return self._ask(("is_running",), self._client.is_running)

    def devices(self):
        return list(self._ask(("devices",), self._client.devices))

    def controls(self, device):
        return list(self._ask(("controls", device), lambda: self._client.controls(device)))

    def refresh(self):
        self._client.refresh()
        self._answers.clear()

    def set_divert(self, device, control, mode):
        raise AssertionError("read-only")

    def reload_rules(self):
        raise AssertionError("read-only")


def first_line(error: Exception) -> str:
    return str(error).splitlines()[0] if str(error) else type(error).__name__


def read_solaar(client: SolaarClient, report: Callable[[SolaarState], None], env=None) -> SolaarState:
    """Read everything, calling `report` with each partial state; returns the final one."""
    env = os.environ if env is None else env
    remembering = _Remembering(client)
    remembering.refresh()
    state = SolaarState()
    try:
        state = replace(state, version=remembering.version())
    except SolaarError as e:
        missing = isinstance(e, SolaarCommandError) and e.returncode is None and "could not run" in str(e)
        state = replace(state, version_error=first_line(e), solaar_missing=missing)
    try:
        state = replace(state, running=remembering.is_running())
    except (SolaarError, OSError):
        pass
    report(state)
    try:
        state = replace(state, devices=tuple(remembering.devices()))
    except SolaarError as e:
        state = replace(state, devices_error=first_line(e))
    report(state)
    context = LintContext.from_client(remembering, env)
    controls = {dc.device: dc.controls for dc in context.devices or ()}
    if context.devices is None and state.devices_error is None:
        state = replace(state, controls_error=context.devices_unavailable)
    return replace(state, done=True, controls=controls, context=context)


def status_lines(state: SolaarState) -> list[str]:
    """What the sidebar says about Solaar, one sentence per line."""
    lines = []
    if state.solaar_missing:
        lines.append(f"Solaar not found ({state.version_error}). Device checks are off; rules and lint still work.")
    elif state.version_error is not None:
        lines.append(f"Could not get the Solaar version: {state.version_error}")
    elif state.version is not None:
        lines.append("Solaar " + ".".join(map(str, state.version)))
    if state.running is False and not state.solaar_missing:
        lines.append("Solaar is not running, so no rules are active.")
    if state.devices_error is not None:
        if not state.solaar_missing:
            lines.append(f"Could not read devices: {state.devices_error}")
    elif state.devices is None:
        lines.append("Reading devices from Solaar…")
    elif not state.devices:
        lines.append("No devices found.")
    elif not state.done:
        lines.append("Reading controls…")
    if state.controls_error is not None:
        lines.append(f"Could not read controls: {state.controls_error}")
    return lines
