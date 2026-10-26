# Heliostat

Heliostat for Solaar: a friendlier rules and diversions editor for Logitech devices on Linux. Solaar owns the HID++ device layer. Heliostat never reimplements it.

- Repo: github.com/rtk94/heliostat
- App ID: io.github.rtk94.Heliostat
- PyPI name: heliostat
- Target: Debian 13, KDE Plasma, Python 3.13+. Supported Solaar versions: 1.1.14 and 1.1.20.

## Where the design lives

- `docs/brief.md`: project overview and v1 scope.
- `docs/decisions.md`: the decision record. Read it before changing anything it covers. Superseded decisions are marked, not deleted.
- `docs/solaar-reference.md`: facts about Solaar internals, verified at the commit it names. Re-verify against Solaar source before relying on it.
- `docs/lint.md`: what each lint check does and what it does not cover.

If a decision changes, update `docs/decisions.md` and this file in the same commit.

## Contributor rules

- Every `.py` file starts with `# SPDX-License-Identifier: GPL-2.0-or-later`.
- Before claiming something about Solaar's behavior, check it in Solaar's source (the pinned checkouts under `.solaar/`, fetched by `make conformance`), not from memory.
- `make test` and `make lint` must pass before a change is committed.
- Automated tests never write to a real `~/.config/solaar/rules.yaml` and never restart a real Solaar.
- If a design rule below turns out to be wrong or impossible, say so explicitly. Do not work around it quietly.
- Attribution: rtk94 is the only author and contributor. No Co-Authored-By or similar trailers in commits, no "Generated with" lines in PRs, no AI credits in files.

## Architecture

```
src/heliostat/
  model/        typed rule components; parse from and serialize to PyYAML structures
  rulesfile/    read, atomic write, backups, external-change detection
  solaar/       SolaarClient protocol; CLI-backed client; parsers; FakeSolaar for tests
  analysis/     lint checks producing Problem objects
  simple/       recognize and generate simple-editor rules (round-trip checked)
  ui/           PySide6 app: device sidebar, rule list, simple and advanced editors, problems panel
  cli.py        `heliostat` (GUI) and `heliostat lint`
tests/
  fixtures/     rules corpora; captured `solaar show` / `solaar config` output per Solaar version
  conformance/  runs pinned Solaar checkouts in subprocesses
tools/          fetch_solaar.sh (pinned checkouts), gen_solaar_names.py, simple_stats.py
```

## Key design rules

- **Model fidelity.** Parse with `yaml.safe_load_all`, the same loader Solaar uses. Anything not recognized is kept as a `Raw` component and written back unchanged. Scalars keep their loaded type: a device serial such as `12345678` loads as an int and must stay one.
- **Semantic conformance.** Heliostat's output must load, on every supported Solaar version, as exactly the rules Heliostat holds.
- **Serialization mirrors Solaar's save** (`diversion._save_config_rule_file`), with two documented deviations:
  - D1: Feature names are written as loaded. Feature conditions Heliostat creates use underscores, because Solaar 1.1.14 cannot load the spaced form its own save writes.
  - D2: Argument shapes are written as loaded, never rewritten to Solaar's canonical shape or fallback. Only components Heliostat creates use Solaar's canonical shapes.
  - Full reasoning for both is in `docs/decisions.md`.
- **Problems are flagged, never silently fixed.** A form that a supported Solaar misloads is preserved on save, and lint reports it with an explicit fix.
- **Broken YAML is read-only.** If `rules.yaml` fails to parse, Heliostat refuses to edit or save it, reports the error location, and warns that Solaar will drop everything after the error on its next save.
- **No Solaar import at runtime.** Solaar code runs only inside the conformance harness, in a subprocess with `XDG_CONFIG_HOME` pointed at a temp directory, because the `diversion` module reads the user's rules file at import time.
- **One seam to Solaar.** All CLI calls go through `SolaarClient`. GUI and lint tests use `FakeSolaar`.
- **CLI output parsing is fragile.** Parsers are built from captured real output, one fixture set per Solaar version. Unknown output fails loudly with the raw text attached. It never guesses.

## Commands

- `make venv`: create `.venv` (Python 3.13) and install `-e ".[dev]"`.
- `make test`, `make lint`, `make fmt`.
- `make conformance`: slow. Fetches the pinned Solaar versions and runs the conformance suite.
