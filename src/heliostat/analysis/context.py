# SPDX-License-Identifier: GPL-2.0-or-later
"""What lint knows about the system: the Solaar version, connected devices and their controls, the session."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from heliostat.analysis.solaar_model import SUPPORTED_TAGS, exact_tag, tag_for_version
from heliostat.solaar import Control, Device, SolaarClient, SolaarError


@dataclass(frozen=True)
class Session:
    """The desktop session. Solaar itself tests WAYLAND_DISPLAY (diversion.wayland); XDG_SESSION_TYPE says
    the same for a normal login and is also checked, in case Heliostat runs without WAYLAND_DISPLAY."""

    wayland: bool = False
    gnome: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Session:
        wayland = env.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(env.get("WAYLAND_DISPLAY"))
        desktops = {d.strip().lower() for d in env.get("XDG_CURRENT_DESKTOP", "").split(":")}
        return cls(wayland=wayland, gnome="gnome" in desktops)


@dataclass(frozen=True)
class DeviceControls:
    device: Device
    controls: tuple[Control, ...]


@dataclass(frozen=True)
class LintContext:
    """`devices` is None when Solaar's device data is unavailable (`devices_unavailable` says why); then
    the device checks (HL001, and the connected-device part of HL002) are skipped with a note. It
    holds online devices only. `version` None means the installed Solaar version is unknown, and the
    version-dependent checks consider every supported version."""

    version: tuple[int, int, int] | None = None
    devices: tuple[DeviceControls, ...] | None = None
    devices_unavailable: str = "no Solaar data given"
    session: Session = field(default_factory=Session)
    notes: tuple[str, ...] = ()

    @classmethod
    def from_client(cls, client: SolaarClient, env: Mapping[str, str] | None = None) -> LintContext:
        env = os.environ if env is None else env
        notes = []
        try:
            version = client.version()
        except SolaarError as e:
            version = None
            notes.append(
                f"could not get the Solaar version ({_first_line(e)}); checking against every supported version"
            )
        try:
            devices = []
            for device in client.devices():
                if device.online:
                    devices.append(DeviceControls(device, tuple(client.controls(device))))
        except SolaarError as e:
            return cls(
                version,
                None,
                f"could not read devices from Solaar: {_first_line(e)}",
                Session.from_env(env),
                tuple(notes),
            )
        return cls(version, tuple(devices), "", Session.from_env(env), tuple(notes))

    @property
    def tags(self) -> tuple[str, ...]:
        """The pinned Solaar tags whose behavior applies: the installed version's, or all if unknown."""
        return (tag_for_version(self.version),) if self.version is not None else SUPPORTED_TAGS

    @property
    def exact(self) -> bool:
        """True if the installed version is one of the pinned tags, so its behavior is checked against source."""
        return self.version is not None and exact_tag(self.version)

    @property
    def version_text(self) -> str:
        return ".".join(map(str, self.version)) if self.version is not None else "unknown"


def _first_line(error: Exception) -> str:
    return str(error).splitlines()[0] if str(error) else type(error).__name__
