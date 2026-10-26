# SPDX-License-Identifier: GPL-2.0-or-later
"""CliSolaarClient with a scripted runner fed from fixtures, and FakeSolaar."""

import subprocess
from pathlib import Path

import pytest

from heliostat.solaar import (
    CliSolaarClient,
    Control,
    Device,
    DeviceNotFound,
    DivertMode,
    FakeSolaar,
    ReloadOutcome,
    ReloadStrategy,
    SolaarClient,
    SolaarCommandError,
    SolaarError,
    SolaarOutputError,
)

V1114 = Path(__file__).parent / "fixtures" / "solaar" / "1.1.14"


def _fixture(name):
    return (V1114 / name).read_text()


class Runner:
    """Answers argv tuples from a script; records every call."""

    def __init__(self, script):
        self.script = dict(script)
        self.calls = []

    def __call__(self, argv, timeout, env):
        self.calls.append((tuple(argv), timeout, env))
        answer = self.script[tuple(argv)]
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, tuple):
            code, out, err = answer
        else:
            code, out, err = 0, answer, ""
        return subprocess.CompletedProcess(argv, code, out, err)


class NoSystem:
    def solaar_processes(self):
        return []


def _client(script, **kwargs):
    runner = Runner(script)
    return CliSolaarClient(runner=runner, system=NoSystem(), **kwargs), runner


SHOW = ("solaar", "show")
MOUSE = ("solaar", "config", "AAAA0002", "divert-keys")


def test_clients_satisfy_the_protocol():
    assert isinstance(CliSolaarClient(system=NoSystem()), SolaarClient)
    assert isinstance(FakeSolaar(), SolaarClient)


def test_version_and_environment():
    client, runner = _client({("solaar", "--version"): _fixture("version.txt")})
    assert client.version() == (1, 1, 14)
    ((_, timeout, env),) = runner.calls
    assert env["LANGUAGE"] == "C" and env["LC_ALL"] == "C.UTF-8"
    assert timeout > 0


def test_devices():
    client, _ = _client({SHOW: _fixture("show_all.txt")})
    devices = client.devices()
    assert [(d.name, d.online) for d in devices] == [
        ("MX MCHNCL", False),
        ("Logi M650", False),
        ("MX Mechanical", True),
        ("Signature M650 Mouse", True),
    ]


def test_controls_use_the_online_pairing():
    client, _ = _client({SHOW: _fixture("show_all.txt")})
    stale, _, _, mouse = client.devices()
    assert stale.serial == "AAAA0001" and not stale.online
    controls = client.controls(stale)  # same serial as the online MX Mechanical: its controls come back
    assert len(controls) == 41
    divertable = [c.name for c in client.controls(mouse) if c.divertable]
    assert divertable == ["Middle Button", "Back Button", "Forward Button"]


def test_controls_report_unknown_gesture_mode_with_saved_mode():
    client, _ = _client({SHOW: _fixture("show_all_back-gestures.txt")})
    mouse = client.devices()[3]
    back = next(c for c in client.controls(mouse) if c.name == "Back Button")
    assert back.mode is DivertMode.DIVERTED_MODE_UNKNOWN and back.mode.value == "diverted (gesture mode unknown)"
    assert back.saved_mode is DivertMode.MOUSE_GESTURES


def test_controls_of_a_device_that_is_not_online():
    client, _ = _client({SHOW: _fixture("show_all.txt").replace("AAAA0002", "AAAA0009")})
    mouse = FakeSolaar.from_show(_fixture("show_all.txt")).devices()[3]
    with pytest.raises(DeviceNotFound):
        client.controls(mouse)


def _shows(runner):
    return sum(argv == SHOW for argv, _, _ in runner.calls)


def test_show_runs_once_for_all_devices():
    client, runner = _client({SHOW: _fixture("show_all.txt")})
    devices = client.devices()
    for device in devices:
        client.controls(device)
    client.devices()
    assert len(devices) == 4 and _shows(runner) == 1


def test_refresh_reads_show_again():
    client, runner = _client({SHOW: _fixture("show_all.txt")})
    client.devices()
    client.refresh()
    runner.script[SHOW] = _fixture("show_all_back-gestures.txt")
    mouse = client.devices()[3]
    back = next(c for c in client.controls(mouse) if c.name == "Back Button")
    assert back.saved_mode is DivertMode.MOUSE_GESTURES
    assert _shows(runner) == 2


def test_failed_show_is_not_kept():
    client, runner = _client({SHOW: (1, "", "boom")})
    with pytest.raises(SolaarCommandError):
        client.devices()
    runner.script[SHOW] = _fixture("show_all.txt")
    assert len(client.devices()) == 4
    assert _shows(runner) == 2


@pytest.mark.parametrize("works", [True, False])
def test_set_divert_forgets_show(works):
    set_back = (*MOUSE, "Back Button", "Mouse Gestures")
    client, runner = _client(
        {
            SHOW: _fixture("show_all.txt"),
            set_back: _fixture("set_mouse_gestures_signature-m650_back.txt") if works else (1, "", "no"),
            MOUSE: _fixture("divert_keys_signature-m650_back-gestures.txt"),
        }
    )
    mouse = client.devices()[3]
    if works:
        client.set_divert(mouse, "Back Button", DivertMode.MOUSE_GESTURES)
    else:
        with pytest.raises(SolaarCommandError):
            client.set_divert(mouse, "Back Button", DivertMode.MOUSE_GESTURES)
    client.devices()
    assert _shows(runner) == 2


def test_reload_rules_forgets_show():
    client, runner = _client({SHOW: _fixture("show_all.txt")})
    client.devices()
    client.reload_rules()
    client.devices()
    assert _shows(runner) == 2


def test_set_divert_runs_config_then_reads_back():
    client, runner = _client(
        {
            (*MOUSE, "Back Button", "Mouse Gestures"): _fixture("set_mouse_gestures_signature-m650_back.txt"),
            MOUSE: _fixture("divert_keys_signature-m650_back-gestures.txt"),
        }
    )
    mouse = FakeSolaar.from_show(_fixture("show_all.txt")).devices()[3]
    client.set_divert(mouse, "Back Button", DivertMode.MOUSE_GESTURES)
    assert [c[0] for c in runner.calls] == [(*MOUSE, "Back Button", "Mouse Gestures"), MOUSE]


def test_set_divert_readback_mismatch_raises():
    client, _ = _client(
        {
            (*MOUSE, "Back Button", "Diverted"): _fixture("set_mouse_gestures_signature-m650_back.txt").replace(
                "NamedInt(2, 'Mouse Gestures')", "NamedInt(1, 'Diverted')"
            ),
            MOUSE: _fixture("divert_keys_signature-m650.txt"),
        }
    )
    mouse = FakeSolaar.from_show(_fixture("show_all.txt")).devices()[3]
    with pytest.raises(SolaarError, match="reads back as 'Regular'"):
        client.set_divert(mouse, "Back Button", DivertMode.DIVERTED)


def test_set_divert_rejects_unsettable_mode_without_running_anything():
    client, runner = _client({})
    mouse = FakeSolaar.from_show(_fixture("show_all.txt")).devices()[3]
    with pytest.raises(ValueError):
        client.set_divert(mouse, "Back Button", DivertMode.DIVERTED_MODE_UNKNOWN)
    assert runner.calls == []


def test_command_failures():
    stderr = "solaar: error: Traceback ...\nException: no online device found matching 'aaaa0002'\n"
    client, _ = _client(
        {
            SHOW: (1, "", stderr),
            ("solaar", "--version"): subprocess.TimeoutExpired("solaar", 15),
            (*MOUSE, "Back Button", "Regular"): FileNotFoundError("solaar"),
        }
    )
    with pytest.raises(SolaarCommandError) as info:
        client.devices()
    assert info.value.returncode == 1 and "no online device" in info.value.stderr
    with pytest.raises(SolaarCommandError, match="timed out"):
        client.version()
    mouse = FakeSolaar.from_show(_fixture("show_all.txt")).devices()[3]
    with pytest.raises(SolaarCommandError, match="could not run"):
        client.set_divert(mouse, "Back Button", DivertMode.REGULAR)


def test_unrecognized_output_propagates():
    client, _ = _client({SHOW: "something else entirely\n"})
    with pytest.raises(SolaarOutputError):
        client.devices()


def test_reload_rules_restart_not_running():
    client, _ = _client({})
    result = client.reload_rules()
    assert result.outcome is ReloadOutcome.NOT_RUNNING and result.ok
    assert result.strategy is ReloadStrategy.RESTART


# ------------------------------------------------------------------------------------------- FakeSolaar


def test_fake_from_show_matches_the_cli_client():
    text = _fixture("show_all.txt")
    fake = FakeSolaar.from_show(text)
    client, _ = _client({SHOW: text})
    assert fake.devices() == client.devices()
    for device in fake.devices()[2:]:
        assert fake.controls(device) == client.controls(device)


def test_fake_set_divert_mirrors_the_real_readback():
    fake = FakeSolaar.from_show(_fixture("show_all.txt"))
    _, _, keyboard, mouse = fake.devices()
    fake.set_divert(mouse, "Back Button", DivertMode.MOUSE_GESTURES)
    back = next(c for c in fake.controls(mouse) if c.name == "Back Button")
    assert back.mode is DivertMode.DIVERTED_MODE_UNKNOWN and back.saved_mode is DivertMode.MOUSE_GESTURES
    fake.set_divert(keyboard, "Calculator", DivertMode.DIVERTED)
    calc = next(c for c in fake.controls(keyboard) if c.name == "Calculator")
    assert calc.mode is DivertMode.DIVERTED
    assert fake.divert_calls == [
        ("AAAA0002", "Back Button", DivertMode.MOUSE_GESTURES),
        ("AAAA0001", "Calculator", DivertMode.DIVERTED),
    ]


def test_fake_set_divert_errors():
    fake = FakeSolaar.from_show(_fixture("show_all.txt"))
    _, _, keyboard, mouse = fake.devices()
    with pytest.raises(SolaarCommandError):
        fake.set_divert(keyboard, "Calculator", DivertMode.MOUSE_GESTURES)  # not raw XY
    with pytest.raises(SolaarCommandError):
        fake.set_divert(mouse, "Left Button", DivertMode.DIVERTED)
    with pytest.raises(SolaarCommandError):
        fake.set_divert(mouse, "Nonexistent", DivertMode.DIVERTED)
    with pytest.raises(DeviceNotFound):
        fake.controls(Device("X", None, "NOPE", None, None, True))
    assert fake.divert_calls == []


def test_fake_reload():
    fake = FakeSolaar(devices=[], controls={"S": [Control("Back Button", True, DivertMode.REGULAR)]})
    assert fake.reload_rules().outcome is ReloadOutcome.RESTARTED
    fake.running = False
    assert fake.reload_rules().outcome is ReloadOutcome.NOT_RUNNING
    assert fake.reload_calls == 2
    assert FakeSolaar(reload_strategy=ReloadStrategy.REMOTE).reload_rules().outcome is ReloadOutcome.UNSUPPORTED
