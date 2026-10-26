# SPDX-License-Identifier: GPL-2.0-or-later
"""`heliostat lint`: output, exit status, and where it gets Solaar data from."""

from pathlib import Path

import pytest

from heliostat import cli
from heliostat.solaar import FakeSolaar

FIXTURES = Path(__file__).parent / "fixtures"
RULES = FIXTURES / "rules"
SHOW = FIXTURES / "solaar" / "1.1.14" / "show_all_back-gestures.txt"


@pytest.fixture(autouse=True)
def _x11(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)


def _run(capsys, *argv):
    code = cli.main(["lint", *map(str, argv)])
    return code, capsys.readouterr()


def test_clean_file_exits_zero(capsys):
    code, out = _run(capsys, RULES / "all-components.yaml", "--no-solaar", "--solaar-version", "1.1.14")
    assert code == 0
    assert out.out.splitlines()[-1].endswith("0 errors, 0 warnings (Solaar 1.1.14, device data unavailable)")
    assert "note HL001: diversion check skipped: --no-solaar given" in out.out


def test_errors_exit_one_with_locations_and_fixes(capsys):
    code, out = _run(capsys, RULES / "lint-cases.yaml", "--solaar-show", SHOW, "--solaar-version", "1.1.14")
    assert code == 1
    lines = out.out.splitlines()
    first = next(line for line in lines if "HL001" in line)
    assert first.startswith(f"{RULES / 'lint-cases.yaml'}:8: error HL001 undiverted-control (rule 1, component 1): ")
    assert "    run: solaar config AAAA0002 divert-keys 'Forward Button' Diverted" in lines
    assert "    fix: use 'Voice Dictation' ('Dictation' is Solaar 1.1.20's name for it)" in lines
    assert lines[-1].endswith("4 errors, 5 warnings (Solaar 1.1.14, 2 connected device(s))")


def test_solaar_show_without_version_checks_every_version(capsys):
    code, out = _run(capsys, RULES / "feature-names.yaml", "--solaar-show", SHOW)
    assert code == 0
    assert "(Solaar unknown, 2 connected device(s))" in out.out
    assert "warning HL007" in out.out


def test_parse_error(capsys):
    code, out = _run(capsys, RULES / "solaar-docs-example.yaml", "--no-solaar")
    assert code == 1
    assert out.out.startswith(f"{RULES / 'solaar-docs-example.yaml'}:18: error HL000 parse-error: ")


def test_missing_file_given_explicitly_exits_two(capsys, tmp_path):
    code, out = _run(capsys, tmp_path / "missing.yaml", "--no-solaar")
    assert code == 2 and "cannot read" in out.err


def test_no_rules_file_at_default_path_exits_zero(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    code, out = _run(capsys)  # no --no-solaar: it must not get as far as asking Solaar
    path = tmp_path / "solaar" / "rules.yaml"
    assert code == 0
    assert out.out == f"no rules file at {path}: Solaar has no user rules, nothing to check\n"
    assert out.err == ""


def test_default_path_is_solaars(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "solaar").mkdir()
    (tmp_path / "solaar" / "rules.yaml").write_text("%YAML 1.3\n---\n- Feature: None\n...\n")
    code, out = _run(capsys, "--no-solaar")
    assert code == 1
    assert f"{tmp_path / 'solaar' / 'rules.yaml'}:3: error HL008 lost-feature" in out.out


def test_default_asks_the_solaar_cli(capsys, monkeypatch):
    import heliostat.solaar

    monkeypatch.setattr(
        heliostat.solaar, "CliSolaarClient", lambda: FakeSolaar.from_show(SHOW.read_text(), version=(1, 1, 14))
    )
    code, out = _run(capsys, RULES / "lint-clean.yaml")
    assert code == 0
    assert out.out.splitlines()[-1].endswith("(Solaar 1.1.14, 2 connected device(s))")


def test_version_needs_a_data_source(capsys):
    with pytest.raises(SystemExit, match="--solaar-version needs"):
        cli.main(["lint", str(RULES / "lint-clean.yaml"), "--solaar-version", "1.1.14"])


def test_bad_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["lint", "--no-solaar", "--solaar-version", "1.1"])
    assert "not a version like 1.1.14" in capsys.readouterr().err
