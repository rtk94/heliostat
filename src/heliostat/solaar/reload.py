# SPDX-License-Identifier: GPL-2.0-or-later
"""Getting a running Solaar to pick up a saved rules.yaml.

Solaar reads rules.yaml once at start (and when its own editor's reload is pressed), so until the
upstream `reload-rules` remote command exists the only way is to restart it:

- If a systemd user service owns the Solaar process (it is the unit's MainPID), run
  `systemctl --user restart <unit>`. KDE and GNOME start XDG autostart entries this way
  (e.g. `app-solaar@autostart.service`).
- Otherwise SIGTERM the process, wait for it to exit, and relaunch it with the same argv, cwd and
  environment, detached (new session, no inherited stdio).

Everything that touches the system goes through `System`, so tests drive the logic with a fake.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from heliostat.solaar.client import ReloadOutcome, ReloadResult, ReloadStrategy

# First Solaar version with the `reload-rules` remote command. None until it lands upstream (Phase 8);
# while it is None, `auto` restarts and `remote` reports UNSUPPORTED.
REMOTE_RELOAD_MIN_VERSION: tuple[int, int, int] | None = None

TERM_TIMEOUT = 10.0  # seconds to wait for Solaar to exit after SIGTERM
SYSTEMCTL_TIMEOUT = 30.0  # for `systemctl --user restart`; it waits for the stop (unit TimeoutStopSec)
START_TIMEOUT = 15.0  # seconds to wait for the restarted unit to report a new main process
SETTLE_TIME = 2.0  # seconds a relaunched Solaar must stay up before it counts as started
POLL_INTERVAL = 0.1

# Solaar's command-line actions (cli.actions). A process with one of these is a short-lived CLI run.
_CLI_ACTIONS = {"show", "probe", "profiles", "config", "pair", "unpair"}
# Solaar's own options (gtk._parse_arguments) that take a value.
_VALUE_OPTIONS = {"-D", "--hidraw", "-w", "--window", "-b", "--battery-icons", "--tray-icon-size"}
_EXIT_OPTIONS = {"-V", "--version", "-h", "--help", "--help-actions"}


def is_solaar_gui_argv(argv: tuple[str, ...] | list[str]) -> bool:
    """True if argv runs the Solaar GUI/tray (the process that runs rules), not a CLI action.

    Matches `solaar ...` and `<python> [python options] .../solaar ...`.
    """
    if not argv:
        return False
    i = 0
    if os.path.basename(argv[0]) != "solaar":
        if not re.fullmatch(r"python[0-9.]*", os.path.basename(argv[0])):
            return False
        i = 1
        while i < len(argv) and argv[i].startswith("-"):
            i += 1
        if i >= len(argv) or os.path.basename(argv[i]) != "solaar":
            return False
    args = argv[i + 1 :]
    j = 0
    while j < len(args):
        arg = args[j]
        if arg in _EXIT_OPTIONS:
            return False
        if arg in _VALUE_OPTIONS:
            j += 2
            continue
        if arg.startswith("-"):
            j += 1  # flags, --opt=value, -dd, -whide
            continue
        return False  # a positional argument is a CLI action (or an error Solaar exits on)
    return True


def user_service_unit(cgroup: str) -> str | None:
    """The systemd user service a process runs directly in, from /proc/<pid>/cgroup (cgroup v2), or None.

    Only a `.service` leaf directly under the user manager's tree counts; scopes (terminals, app
    launchers' transient scopes) cannot be restarted.
    """
    for line in cgroup.splitlines():
        if not line.startswith("0::"):
            continue
        parts = [p for p in line[3:].split("/") if p]
        if not any(re.fullmatch(r"user@\d+\.service", p) for p in parts):
            return None
        leaf = parts[-1]
        if leaf.endswith(".service") and not re.fullmatch(r"user@\d+\.service", leaf):
            return leaf
        return None
    return None


def parse_systemctl_show(text: str) -> dict[str, str]:
    props = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            props[key] = value
    return props


@dataclass(frozen=True)
class SolaarProcess:
    pid: int
    argv: tuple[str, ...]
    start_time: int  # /proc/<pid>/stat starttime, to tell a reused PID apart
    cwd: str | None
    environ: dict[str, str] | None
    cgroup: str | None


class Spawned(Protocol):
    """A started process (subprocess.Popen satisfies this)."""

    pid: int

    def poll(self) -> int | None: ...


class System(Protocol):
    def solaar_processes(self) -> list[SolaarProcess]: ...

    def has_exited(self, process: SolaarProcess) -> bool: ...

    def terminate(self, pid: int) -> None: ...

    def spawn(self, argv: tuple[str, ...], cwd: str, env: dict[str, str]) -> Spawned:
        """Start a detached process: new session, stdio on /dev/null."""
        ...

    def systemctl(self, *args: str, timeout: float) -> subprocess.CompletedProcess: ...

    def sleep(self, seconds: float) -> None: ...

    def monotonic(self) -> float: ...


class RealSystem:
    """The running system: /proc, signals, subprocess, systemctl. Only ever used outside automated tests."""

    def __init__(self, proc: Path = Path("/proc")):
        self.proc = proc

    def _read(self, pid: int, name: str) -> bytes | None:
        try:
            return (self.proc / str(pid) / name).read_bytes()
        except OSError:
            return None

    def _start_time(self, pid: int) -> tuple[str, int] | None:
        stat = self._read(pid, "stat")
        if stat is None:
            return None
        fields = stat.decode(errors="replace").rpartition(")")[2].split()
        return fields[0], int(fields[19])  # state, starttime (fields 3 and 22 of proc_pid_stat(5))

    def solaar_processes(self) -> list[SolaarProcess]:
        found = []
        uid = os.getuid()
        for entry in self.proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            pid = int(entry.name)
            try:
                if entry.stat().st_uid != uid:
                    continue
            except OSError:
                continue
            cmdline = self._read(pid, "cmdline")
            if not cmdline:
                continue
            argv = tuple(a.decode(errors="surrogateescape") for a in cmdline.rstrip(b"\0").split(b"\0"))
            if not is_solaar_gui_argv(argv):
                continue
            state = self._start_time(pid)
            if state is None or state[0] in ("Z", "X"):
                continue
            try:
                cwd = os.readlink(self.proc / str(pid) / "cwd")
            except OSError:
                cwd = None
            environ_raw = self._read(pid, "environ")
            environ = None
            if environ_raw:
                environ = {}
                for item in environ_raw.rstrip(b"\0").split(b"\0"):
                    key, sep, value = item.decode(errors="surrogateescape").partition("=")
                    if sep:
                        environ[key] = value
            cgroup = self._read(pid, "cgroup")
            found.append(
                SolaarProcess(pid, argv, state[1], cwd, environ, cgroup.decode(errors="replace") if cgroup else None)
            )
        return found

    def has_exited(self, process: SolaarProcess) -> bool:
        state = self._start_time(process.pid)
        return state is None or state[1] != process.start_time or state[0] in ("Z", "X")

    def terminate(self, pid: int) -> None:
        os.kill(pid, signal.SIGTERM)

    def spawn(self, argv, cwd, env):
        return subprocess.Popen(
            list(argv),
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

    def systemctl(self, *args, timeout):
        return subprocess.run(
            ["systemctl", "--user", *args], capture_output=True, text=True, timeout=timeout, check=False
        )

    def sleep(self, seconds):
        time.sleep(seconds)

    def monotonic(self):
        return time.monotonic()


class _Log:
    def __init__(self, strategy: ReloadStrategy):
        self.strategy = strategy
        self.steps: list[str] = []
        self.fields: dict = {}

    def step(self, text: str):
        self.steps.append(text)

    def result(self, outcome: ReloadOutcome, message: str) -> ReloadResult:
        return ReloadResult(outcome, self.strategy, message, steps=tuple(self.steps), **self.fields)


def reload_rules(strategy: ReloadStrategy, version: Callable[[], tuple[int, int, int]], system: System) -> ReloadResult:
    log = _Log(strategy)
    if strategy is ReloadStrategy.RESTART:
        return _restart(system, log)
    if REMOTE_RELOAD_MIN_VERSION is None:
        if strategy is ReloadStrategy.REMOTE:
            return log.result(ReloadOutcome.UNSUPPORTED, "no Solaar release has a reload-rules remote command yet")
        log.step("auto: no Solaar release has a reload-rules remote command yet; restarting instead")
        return _restart(system, log)
    installed = version()
    if installed < REMOTE_RELOAD_MIN_VERSION:
        gate = ".".join(map(str, REMOTE_RELOAD_MIN_VERSION))
        message = f"Solaar {'.'.join(map(str, installed))} predates the reload-rules command ({gate})"
        if strategy is ReloadStrategy.REMOTE:
            return log.result(ReloadOutcome.UNSUPPORTED, message)
        log.step(f"auto: {message}; restarting instead")
        return _restart(system, log)
    # The command's shape is agreed with Solaar's maintainers in Phase 8; nothing to send until then.
    return log.result(ReloadOutcome.UNSUPPORTED, "the reload-rules remote command is not implemented yet")


def _wait(system: System, timeout: float, done: Callable[[], bool]) -> bool:
    deadline = system.monotonic() + timeout
    while True:
        if done():
            return True
        if system.monotonic() >= deadline:
            return False
        system.sleep(POLL_INTERVAL)


def _restart(system: System, log: _Log) -> ReloadResult:
    processes = system.solaar_processes()
    if not processes:
        log.step("no Solaar GUI process found for this user")
        return log.result(ReloadOutcome.NOT_RUNNING, "Solaar is not running; it reads rules.yaml when it next starts")
    if len(processes) > 1:
        pids = ", ".join(str(p.pid) for p in processes)
        log.step(f"found {len(processes)} Solaar GUI processes: {pids}")
        return log.result(ReloadOutcome.FAILED, f"more than one Solaar process ({pids}); not restarting any")
    process = processes[0]
    log.fields.update(old_pid=process.pid, argv=process.argv)
    log.step(f"found Solaar pid {process.pid}: {' '.join(process.argv)}")

    unit = user_service_unit(process.cgroup or "")
    if unit is not None:
        log.fields["unit"] = unit
        log.step(f"pid {process.pid} is in systemd user unit {unit}")
        return _restart_unit(system, log, process, unit)
    log.step(f"pid {process.pid} is not in a systemd user service (cgroup: {(process.cgroup or '?').strip()})")
    return _restart_signal(system, log, process)


def _unit_props(system: System, unit: str) -> dict[str, str]:
    done = system.systemctl("show", "--property=Id,MainPID,ActiveState,SubState", unit, timeout=SYSTEMCTL_TIMEOUT)
    return parse_systemctl_show(done.stdout) if done.returncode == 0 else {}


def _restart_unit(system: System, log: _Log, process: SolaarProcess, unit: str) -> ReloadResult:
    log.fields["method"] = "systemd"
    props = _unit_props(system, unit)
    log.step(f"systemctl --user show {unit}: MainPID={props.get('MainPID')} ActiveState={props.get('ActiveState')}")
    if props.get("MainPID") != str(process.pid):
        return log.result(
            ReloadOutcome.FAILED,
            f"{unit} does not have Solaar (pid {process.pid}) as its main process; not restarting it",
        )
    log.step(f"running: systemctl --user restart {unit}")
    try:
        done = system.systemctl("restart", unit, timeout=SYSTEMCTL_TIMEOUT)
    except subprocess.TimeoutExpired:
        message = f"systemctl --user restart {unit} timed out after {SYSTEMCTL_TIMEOUT} s"
        return log.result(ReloadOutcome.FAILED, message)
    if done.returncode != 0:
        log.step(f"systemctl exited {done.returncode}: {done.stderr.strip()}")
        return log.result(ReloadOutcome.FAILED, f"systemctl --user restart {unit} failed")

    def started():
        props.clear()
        props.update(_unit_props(system, unit))
        return props.get("ActiveState") == "active" and props.get("MainPID") not in (None, "0", str(process.pid))

    if not _wait(system, START_TIMEOUT, started):
        log.step(f"after {START_TIMEOUT} s: MainPID={props.get('MainPID')} ActiveState={props.get('ActiveState')}")
        return log.result(ReloadOutcome.FAILED, f"{unit} did not come back with a new Solaar process")
    new_pid = int(props["MainPID"])
    log.fields["new_pid"] = new_pid
    log.step(f"{unit} is active with new MainPID {new_pid}")
    if not system.has_exited(process):
        return log.result(ReloadOutcome.FAILED, f"old Solaar pid {process.pid} is still running next to {new_pid}")
    return log.result(ReloadOutcome.RESTARTED, f"restarted {unit}: Solaar pid {process.pid} -> {new_pid}")


def _restart_signal(system: System, log: _Log, process: SolaarProcess) -> ReloadResult:
    log.fields["method"] = "signal"
    log.step(f"sending SIGTERM to pid {process.pid}")
    try:
        system.terminate(process.pid)
    except ProcessLookupError:
        log.step(f"pid {process.pid} was already gone")
    except PermissionError as e:
        return log.result(ReloadOutcome.FAILED, f"cannot signal pid {process.pid}: {e}")
    if not _wait(system, TERM_TIMEOUT, lambda: system.has_exited(process)):
        return log.result(
            ReloadOutcome.FAILED,
            f"Solaar pid {process.pid} did not exit within {TERM_TIMEOUT} s of SIGTERM; not relaunched "
            "(it is still running, with the old rules)",
        )
    log.step(f"pid {process.pid} exited")

    cwd = process.cwd or os.path.expanduser("~")
    if process.environ is not None:
        env = process.environ
        log.step("relaunching with the old process's environment")
    else:
        env = dict(os.environ)
        log.step("old process's environment unreadable; relaunching with Heliostat's environment")
    log.step(f"relaunching detached in {cwd}: {' '.join(process.argv)}")
    try:
        child = system.spawn(process.argv, cwd, env)
    except OSError as e:
        return log.result(ReloadOutcome.FAILED, f"could not relaunch Solaar: {e}")
    new_pid = child.pid
    log.fields["new_pid"] = new_pid
    _wait(system, SETTLE_TIME, lambda: child.poll() is not None)
    code = child.poll()
    if code is not None:
        log.step(f"relaunched Solaar pid {new_pid} exited with status {code}")
        return log.result(ReloadOutcome.FAILED, f"relaunched Solaar exited with status {code}; Solaar is not running")
    log.step(f"pid {new_pid} still running after {SETTLE_TIME} s")
    return log.result(ReloadOutcome.RESTARTED, f"restarted Solaar: pid {process.pid} -> {new_pid}")
