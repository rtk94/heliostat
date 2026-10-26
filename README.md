# Heliostat for Solaar

A friendlier rules and diversions editor for Logitech devices on Linux. Heliostat edits Solaar's own `~/.config/solaar/rules.yaml` and relies on Solaar for everything device-related. You can stop using Heliostat at any time and lose nothing.

**Status:** pre-alpha. The read-only editor and `heliostat lint` work. Editing and saving are in progress. The reload step (Apply) has not been verified end to end.

## What it does

- Shows every rule in a Solaar rules file: in plain language where the rule has a simple shape, and as a full tree where it does not.
- Lints the file against your installed Solaar: wrong or unknown control names, Feature names that Solaar 1.1.14 cannot load, rules that can never fire, and rules that target controls your device is not diverting.
- Never rewrites a rule to a different form unless you edit it. Forms Solaar would damage on its own save are flagged, not silently changed.

One-click divert is planned but not built yet.

## Requirements

- Debian 13 with Solaar 1.1.14, or Solaar 1.1.20.
- Python 3.13 or later.
- PySide6 (Qt 6), installed automatically.

## Install

From a checkout:

```
pipx install .
```

## Usage

```
heliostat                    # open the editor on ~/.config/solaar/rules.yaml
heliostat --rules FILE       # open a different rules file
heliostat lint [PATH]        # check a rules file; exit 1 on errors, 2 if unreadable
heliostat --version
```

`heliostat lint` runs read-only. It asks the installed `solaar` CLI for its version and connected devices. Use `--no-solaar` to skip device checks, `--solaar-show FILE` to read device data from saved `solaar show` output, or `--solaar-version X.Y.Z` to name the Solaar version to check against.

## Development

```
make venv         # create .venv (Python 3.13) with dev dependencies
make test         # unit tests
make lint         # ruff check and format check
make conformance  # tests against pinned Solaar versions (fetches Solaar from GitHub)
```

`docs/` holds the design record: `brief.md` (overview), `decisions.md` (why things are the way they are), `solaar-reference.md` (verified facts about Solaar internals), and `lint.md` (what each check does and does not cover).

## Independence

Heliostat is an independent project. It is not affiliated with the Solaar project or with Logitech.

## License

GPL-2.0-or-later. See `LICENSE`.
