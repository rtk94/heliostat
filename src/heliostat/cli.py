# SPDX-License-Identifier: GPL-2.0-or-later
"""Command-line entry point. With no subcommand it opens the GUI."""

import argparse
import os
import shlex
import sys
from pathlib import Path

from heliostat import __version__


def default_rules_path() -> Path:
    """Where Solaar reads its rules: $XDG_CONFIG_HOME/solaar/rules.yaml (diversion._file_path)."""
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(os.path.join("~", ".config"))
    return Path(config) / "solaar" / "rules.yaml"


def _version(text: str) -> tuple[int, int, int]:
    try:
        major, minor, patch = (int(p) for p in text.split("."))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a version like 1.1.14: {text!r}") from None
    return major, minor, patch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="heliostat",
        description="With no command, open the rules editor.",
    )
    parser.add_argument("--version", action="version", version=f"heliostat {__version__}")
    parser.add_argument(
        "--rules", type=Path, metavar="FILE", help=f"rules file the editor opens (default: {default_rules_path()})"
    )
    sub = parser.add_subparsers(dest="command")
    reload_parser = sub.add_parser(
        "debug-reload",
        help="get the running Solaar to reload rules.yaml (restarts it) and print what happened",
    )
    reload_parser.add_argument("--strategy", choices=["auto", "remote", "restart"], default="restart")
    lint_parser = sub.add_parser(
        "lint",
        help="check a rules file for problems (read-only); exit status 1 if there are errors",
        description="Check a Solaar rules file. Reads the file and asks the `solaar` CLI about the installed "
        "version and connected devices; changes nothing. Exit status: 0 no errors (or no rules file at the "
        "default path), 1 errors, 2 the file could not be read.",
    )
    lint_parser.add_argument("path", nargs="?", type=Path, help=f"rules file (default: {default_rules_path()})")
    source = lint_parser.add_mutually_exclusive_group()
    source.add_argument("--no-solaar", action="store_true", help="do not run solaar: skip the device checks")
    source.add_argument(
        "--solaar-show",
        type=Path,
        metavar="FILE",
        help="read device data from saved `solaar show` output instead of running solaar",
    )
    lint_parser.add_argument(
        "--solaar-version",
        type=_version,
        metavar="X.Y.Z",
        help="the Solaar version to check against (with --no-solaar or --solaar-show; default: unknown)",
    )
    return parser


def _debug_reload(strategy: str) -> int:
    from heliostat.solaar import CliSolaarClient, ReloadStrategy

    result = CliSolaarClient(reload_strategy=ReloadStrategy(strategy)).reload_rules()
    print(result)
    return 0 if result.ok else 1


def _lint_context(args):
    from heliostat.analysis import LintContext, Session
    from heliostat.solaar import CliSolaarClient, FakeSolaar

    if args.no_solaar:
        return LintContext(
            version=args.solaar_version,
            devices=None,
            devices_unavailable="--no-solaar given",
            session=Session.from_env(os.environ),
        )
    if args.solaar_show is not None:
        version = args.solaar_version or (0, 0, 0)
        client = FakeSolaar.from_show(args.solaar_show.read_text(), version=version)
        context = LintContext.from_client(client)
        return context if args.solaar_version else _replace(context, version=None)
    if args.solaar_version is not None:
        raise SystemExit("heliostat lint: --solaar-version needs --no-solaar or --solaar-show")
    return LintContext.from_client(CliSolaarClient())


def _replace(context, **changes):
    import dataclasses

    return dataclasses.replace(context, **changes)


def _where(rule_path: tuple[int, ...]) -> str:
    if not rule_path:
        return ""
    where = f"rule {rule_path[0] + 1}"
    if len(rule_path) > 1:
        where += ", component " + ".".join(str(i + 1) for i in rule_path[1:])
    return where


def _lint(args) -> int:
    from heliostat.analysis import Severity, lint_ruleset, locations
    from heliostat.analysis.lint import _parse_error
    from heliostat.rulesfile import RulesParseError, loads

    path = args.path or default_rules_path()
    if args.path is None and not path.exists():
        # Solaar runs with no user rules when its rules file does not exist (diversion.load_config_rule_file).
        print(f"no rules file at {path}: Solaar has no user rules, nothing to check")
        return 0
    try:
        data = path.read_bytes()
    except OSError as e:
        print(f"heliostat lint: cannot read {path}: {e.strerror or e}", file=sys.stderr)
        return 2
    lines = {}
    try:
        ruleset = loads(data, path)
    except RulesParseError as e:
        problems = [_parse_error(e)]
        lines[()] = e.line
        context = None
    else:
        context = _lint_context(args)
        problems = lint_ruleset(ruleset, context)
        lines = locations(data, ruleset)
    for p in problems:
        if p.severity is Severity.NOTE:
            code = f" {p.code}" if p.code else ""
            print(f"{path}: note{code}: {p.message}")
            continue
        line = lines.get(p.rule_path)
        where = f"{path}:{line}" if line else str(path)
        rule = f" ({_where(p.rule_path)})" if p.rule_path else ""
        print(f"{where}: {p.severity.value} {p.code} {p.name}{rule}: {p.message}")
        if p.fix is not None:
            print(f"    fix: {p.fix.description}")
            if p.fix.command:
                print(f"    run: {shlex.join(p.fix.command)}")
    errors = sum(p.severity is Severity.ERROR for p in problems)
    warnings = sum(p.severity is Severity.WARNING for p in problems)
    summary = f"{errors} error{'s' * (errors != 1)}, {warnings} warning{'s' * (warnings != 1)}"
    if context is not None:
        devices = (
            "device data unavailable" if context.devices is None else f"{len(context.devices)} connected device(s)"
        )
        summary += f" (Solaar {context.version_text}, {devices})"
    print(f"{path}: {summary}")
    return 1 if errors else 0


def _gui(args) -> int:
    from heliostat.solaar import CliSolaarClient
    from heliostat.ui.app import run

    return run(args.rules or default_rules_path(), CliSolaarClient())


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "debug-reload":
        return _debug_reload(args.strategy)
    if args.command == "lint":
        return _lint(args)
    return _gui(args)


if __name__ == "__main__":
    raise SystemExit(main())
