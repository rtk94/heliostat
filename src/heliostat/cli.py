# SPDX-License-Identifier: GPL-2.0-or-later
"""Command-line entry point. Phase 0 stub: prints the version."""

from heliostat import __version__


def main() -> int:
    print(f"heliostat {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
