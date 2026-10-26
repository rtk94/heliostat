# SPDX-License-Identifier: GPL-2.0-or-later
import pytest

import heliostat
from heliostat.cli import main


def test_version_is_set():
    assert heliostat.__version__


def test_cli_prints_version(capsys):
    with pytest.raises(SystemExit) as exit:
        main(["--version"])
    assert exit.value.code == 0
    assert capsys.readouterr().out.strip() == f"heliostat {heliostat.__version__}"
