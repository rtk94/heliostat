# SPDX-License-Identifier: GPL-2.0-or-later
"""Run tests/conformance/solaar_runner.py against a pinned Solaar checkout in a subprocess."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SOLAAR_DIR = REPO_ROOT / ".solaar"
SOLAAR_TAGS = ("1.1.14", "1.1.20")
RUNNER = Path(__file__).resolve().with_name("solaar_runner.py")
RULES_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "rules"

DEFAULT_SOLAAR_PYTHON = "/usr/bin/python3"


def solaar_python() -> str:
    return os.environ.get("HELIOSTAT_SOLAAR_PYTHON", DEFAULT_SOLAAR_PYTHON)


def solaar_lib(tag: str) -> Path:
    """Return .solaar/<tag>/lib, skipping the test if the checkout is missing."""
    lib = SOLAAR_DIR / tag / "lib"
    if not (lib / "logitech_receiver" / "diversion.py").is_file():
        pytest.skip(f"Solaar {tag} not checked out at {lib.parent}; run tools/fetch_solaar.sh")
    return lib


def run_runner(tag: str, *args: str) -> subprocess.CompletedProcess:
    """Run solaar_runner.py under Solaar <tag> with a fresh XDG_CONFIG_HOME and no display."""
    lib = solaar_lib(tag)
    python = solaar_python()
    if shutil.which(python) is None:
        pytest.skip(f"Solaar interpreter {python} not found; set HELIOSTAT_SOLAAR_PYTHON")
    with tempfile.TemporaryDirectory(prefix=f"heliostat-solaar-{tag}-") as tmp:
        config = Path(tmp) / "config"
        config.mkdir()
        # A minimal environment: no DISPLAY / WAYLAND_DISPLAY / DBUS session, so Solaar's X11 and
        # GNOME focus lookups fail fast with a warning instead of touching the user's session.
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": tmp,
            "LANG": "C.UTF-8",
            "XDG_CONFIG_HOME": str(config),
            "PYTHONPATH": str(lib),
        }
        return subprocess.run(
            [python, "-s", str(RUNNER), *args],
            env=env,
            cwd=tmp,
            capture_output=True,
            text=True,
            timeout=60,
        )


def solaar_roundtrip(tag: str, in_path: Path, out_path: Path) -> bytes:
    """Load and save in_path with Solaar <tag>, writing out_path; return the saved bytes."""
    result = run_runner(tag, "roundtrip", str(in_path), str(out_path))
    assert result.returncode == 0, (
        f"Solaar {tag} roundtrip of {in_path.name} failed (exit {result.returncode}):\n{result.stderr}"
    )
    return out_path.read_bytes()
