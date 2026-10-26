# SPDX-License-Identifier: GPL-2.0-or-later
"""reload_rules(): strategies, the systemd and signal restart paths, and process discovery. All against fakes."""

import os
import subprocess

import pytest

from heliostat.solaar import ReloadOutcome, ReloadStrategy, reload
from heliostat.solaar.reload import (
    RealSystem,
    SolaarProcess,
    is_solaar_gui_argv,
    parse_systemctl_show,
    reload_rules,
    user_service_unit,
)

UNIT = "app-solaar@autostart.service"
UNIT_CGROUP = f"0::/user.slice/user-1000.slice/user@1000.service/app.slice/{UNIT}\n"
SCOPE_CGROUP = "0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-ghostty-surface-transient-1.scope\n"
ARGV = ("/usr/bin/python3", "/usr/bin/solaar", "--window=hide")


def _process(pid=14327, cgroup=UNIT_CGROUP, environ=None):
    return SolaarProcess(pid, ARGV, 1000, "/home/user", environ if environ is not None else {"DISPLAY": ":0"}, cgroup)


class Child:
    def __init__(self, pid, exit_after=None, clock=None):
        self.pid = pid
        self.exit_after = exit_after
        self.clock = clock

    def poll(self):
        if self.exit_after is not None and self.clock.now >= self.exit_after:
            return 1
        return None


class FakeSystem:
    """Scripted process table and systemd. Time only moves when the code under test sleeps."""

    def __init__(self, processes=(), main_pid="14327", restart_code=0, new_main_pid="20000", exits_on_term=True):
        self.processes = list(processes)
        self.main_pid = main_pid
        self.restart_code = restart_code
        self.new_main_pid = new_main_pid
        self.exits_on_term = exits_on_term
        self.now = 0.0
        self.calls = []
        self.exited = set()
        self.restarted = False
        self.child_exit_after = None

    def solaar_processes(self):
        return [p for p in self.processes if p.pid not in self.exited]

    def has_exited(self, process):
        return process.pid in self.exited

    def terminate(self, pid):
        self.calls.append(("terminate", pid))
        if self.exits_on_term:
            self.exited.add(pid)

    def spawn(self, argv, cwd, env):
        self.calls.append(("spawn", argv, cwd, env))
        return Child(30000, self.child_exit_after, self)

    def systemctl(self, *args, timeout):
        self.calls.append(("systemctl", *args))
        if args[0] == "show":
            pid = self.new_main_pid if self.restarted else self.main_pid
            state = "active" if pid != "0" else "activating"
            return subprocess.CompletedProcess(args, 0, f"Id={UNIT}\nMainPID={pid}\nActiveState={state}\n", "")
        if args[0] == "restart":
            if self.restart_code == 0:
                self.restarted = True
                self.exited.update(p.pid for p in self.processes)
            return subprocess.CompletedProcess(args, self.restart_code, "", "Failed to restart" * self.restart_code)
        raise AssertionError(args)

    def sleep(self, seconds):
        self.now += seconds

    def monotonic(self):
        return self.now


def _never_called():
    raise AssertionError("version() should not be needed")


def _reload(system, strategy=ReloadStrategy.RESTART, version=_never_called):
    return reload_rules(strategy, version, system)


# -------------------------------------------------------------------------------------------- systemd


def test_systemd_restart():
    system = FakeSystem([_process()])
    result = _reload(system)
    assert result.outcome is ReloadOutcome.RESTARTED and result.ok
    assert (result.method, result.unit, result.old_pid, result.new_pid) == ("systemd", UNIT, 14327, 20000)
    assert result.argv == ARGV
    assert ("systemctl", "restart", UNIT) in system.calls
    assert not any(c[0] in ("terminate", "spawn") for c in system.calls)
    assert "systemctl --user restart app-solaar@autostart.service" in str(result)


def test_systemd_unit_whose_main_pid_is_not_solaar_is_left_alone():
    system = FakeSystem([_process()], main_pid="999")
    result = _reload(system)
    assert result.outcome is ReloadOutcome.FAILED and "not restarting" in result.message
    assert [c[1] for c in system.calls] == ["show"]


def test_systemd_restart_failure():
    system = FakeSystem([_process()], restart_code=1)
    result = _reload(system)
    assert result.outcome is ReloadOutcome.FAILED and not result.ok


def test_systemd_unit_that_does_not_come_back():
    system = FakeSystem([_process()], new_main_pid="0")
    result = _reload(system)
    assert result.outcome is ReloadOutcome.FAILED and "did not come back" in result.message
    assert system.now >= reload.START_TIMEOUT


# ------------------------------------------------------------------------------------- signal relaunch


def test_signal_restart_outside_systemd():
    system = FakeSystem([_process(cgroup=SCOPE_CGROUP, environ={"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"})])
    result = _reload(system)
    assert result.outcome is ReloadOutcome.RESTARTED
    assert (result.method, result.unit, result.old_pid, result.new_pid) == ("signal", None, 14327, 30000)
    assert system.calls == [
        ("terminate", 14327),
        ("spawn", ARGV, "/home/user", {"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}),
    ]


def test_signal_restart_without_readable_environment_uses_heliostats():
    system = FakeSystem([_process(cgroup=None, environ={})])
    system.processes = [SolaarProcess(14327, ARGV, 1000, None, None, None)]
    result = _reload(system)
    assert result.outcome is ReloadOutcome.RESTARTED
    _, argv, cwd, env = system.calls[1]
    assert cwd == os.path.expanduser("~") and env == dict(os.environ)


def test_solaar_that_ignores_sigterm_is_not_relaunched():
    system = FakeSystem([_process(cgroup=SCOPE_CGROUP)], exits_on_term=False)
    result = _reload(system)
    assert result.outcome is ReloadOutcome.FAILED and "did not exit" in result.message
    assert system.calls == [("terminate", 14327)]
    assert system.now >= reload.TERM_TIMEOUT


def test_relaunched_solaar_that_exits_immediately():
    system = FakeSystem([_process(cgroup=SCOPE_CGROUP)])
    system.child_exit_after = 0.5
    result = _reload(system)
    assert result.outcome is ReloadOutcome.FAILED and "exited with status 1" in result.message


# ------------------------------------------------------------------------------------ other situations


def test_not_running():
    result = _reload(FakeSystem([]))
    assert result.outcome is ReloadOutcome.NOT_RUNNING and result.ok


def test_two_solaar_processes_are_not_touched():
    system = FakeSystem([_process(1), _process(2)])
    result = _reload(system)
    assert result.outcome is ReloadOutcome.FAILED and system.calls == []


def test_strategies_while_remote_command_does_not_exist():
    assert reload.REMOTE_RELOAD_MIN_VERSION is None
    remote = _reload(FakeSystem([_process()]), ReloadStrategy.REMOTE)
    assert remote.outcome is ReloadOutcome.UNSUPPORTED and not remote.ok
    auto = _reload(FakeSystem([_process()]), ReloadStrategy.AUTO)
    assert auto.outcome is ReloadOutcome.RESTARTED and auto.strategy is ReloadStrategy.AUTO
    assert auto.steps[0].startswith("auto: no Solaar release")


def test_strategies_with_a_version_gate(monkeypatch):
    monkeypatch.setattr(reload, "REMOTE_RELOAD_MIN_VERSION", (1, 1, 21))
    old = _reload(FakeSystem([_process()]), ReloadStrategy.AUTO, version=lambda: (1, 1, 14))
    assert old.outcome is ReloadOutcome.RESTARTED and "predates" in old.steps[0]
    remote_old = _reload(FakeSystem([_process()]), ReloadStrategy.REMOTE, version=lambda: (1, 1, 14))
    assert remote_old.outcome is ReloadOutcome.UNSUPPORTED


# -------------------------------------------------------------------------------------- pure helpers


@pytest.mark.parametrize(
    "argv, gui",
    [
        (ARGV, True),
        (("/usr/bin/solaar",), True),
        (("solaar", "-w", "hide", "-dd"), True),
        (("python3.13", "-u", "/home/x/Solaar/bin/solaar", "--hidraw", "/dev/hidraw2"), True),
        (("/usr/bin/python3", "/usr/bin/solaar", "show"), False),
        (("/usr/bin/python3", "/usr/bin/solaar", "config", "AAAA0002", "divert-keys"), False),
        (("/usr/bin/solaar", "--version"), False),
        (("/usr/bin/python3", "/usr/bin/heliostat"), False),
        (("/usr/bin/python3",), False),
        (("bash", "-c", "solaar"), False),
        ((), False),
    ],
)
def test_is_solaar_gui_argv(argv, gui):
    assert is_solaar_gui_argv(argv) is gui


@pytest.mark.parametrize(
    "cgroup, unit",
    [
        (UNIT_CGROUP, UNIT),
        (SCOPE_CGROUP, None),
        ("0::/user.slice/user-1000.slice/session-2.scope\n", None),
        ("0::/user.slice/user-1000.slice/user@1000.service\n", None),
        ("0::/system.slice/solaar.service\n", None),
        ("12:pids:/foo\n1:name=systemd:/bar\n", None),
        ("", None),
    ],
)
def test_user_service_unit(cgroup, unit):
    assert user_service_unit(cgroup) == unit


def test_parse_systemctl_show():
    text = "Id=app-solaar@autostart.service\nMainPID=14327\nActiveState=active\nExecStart={ path=/a ; x=y }\n"
    props = parse_systemctl_show(text)
    assert props["MainPID"] == "14327" and props["ExecStart"] == "{ path=/a ; x=y }"


def _fake_proc_entry(root, pid, argv, state="S", starttime=777, cgroup=UNIT_CGROUP):
    d = root / str(pid)
    d.mkdir()
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    fields = [state, "1", "1", "1"] + ["0"] * 15 + [str(starttime)] + ["0"] * 10
    (d / "stat").write_text(f"{pid} (solaar) {' '.join(fields)}\n")
    (d / "environ").write_bytes(b"DISPLAY=:0\0HOME=/home/user\0")
    (d / "cgroup").write_text(cgroup)
    (d / "cwd").symlink_to(root)


def test_real_system_reads_a_proc_tree(tmp_path):
    _fake_proc_entry(tmp_path, 14327, ARGV)
    _fake_proc_entry(tmp_path, 200, ("/usr/bin/python3", "/usr/bin/solaar", "show"))
    _fake_proc_entry(tmp_path, 300, ARGV, state="Z")
    _fake_proc_entry(tmp_path, 400, ("/usr/bin/bash",))
    (tmp_path / "self").mkdir()
    system = RealSystem(tmp_path)
    (found,) = system.solaar_processes()
    assert found == SolaarProcess(14327, ARGV, 777, str(tmp_path), {"DISPLAY": ":0", "HOME": "/home/user"}, UNIT_CGROUP)
    assert not system.has_exited(found)
    (tmp_path / "14327" / "stat").write_text("14327 (solaar) S " + "0 " * 18 + "999\n")  # pid reused
    assert system.has_exited(found)
    assert system.has_exited(SolaarProcess(5, ARGV, 1, None, None, None))  # no such pid
