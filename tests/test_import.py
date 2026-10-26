# SPDX-License-Identifier: GPL-2.0-or-later
import heliostat
from heliostat.cli import main


def test_version_is_set():
    assert heliostat.__version__


def test_cli_prints_version(capsys):
    assert main() == 0
    assert capsys.readouterr().out.strip() == f"heliostat {heliostat.__version__}"
