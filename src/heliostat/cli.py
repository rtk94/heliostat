# SPDX-License-Identifier: GPL-2.0-or-later
"""Command-line entry point. With no subcommand it prints the version (the GUI comes in a later phase)."""

import argparse
import sys

from heliostat import __version__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="heliostat")
    sub = parser.add_subparsers(dest="command")
    reload_parser = sub.add_parser(
        "debug-reload",
        help="get the running Solaar to reload rules.yaml (restarts it) and print what happened",
    )
    reload_parser.add_argument("--strategy", choices=["auto", "remote", "restart"], default="restart")
    return parser


def _debug_reload(strategy: str) -> int:
    from heliostat.solaar import CliSolaarClient, ReloadStrategy

    result = CliSolaarClient(reload_strategy=ReloadStrategy(strategy)).reload_rules()
    print(result)
    return 0 if result.ok else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "debug-reload":
        return _debug_reload(args.strategy)
    print(f"heliostat {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
