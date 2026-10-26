# Heliostat

A friendlier rules and diversions editor for Logitech devices on Linux, built on top of Solaar. Solaar owns the HID++ device layer; Heliostat never reimplements it.

Repo: github.com/rtk94/heliostat. App ID: io.github.rtk94.Heliostat. PyPI name: heliostat.

## How work is organized

- `prompts/` holds one prompt file per build phase. A session is started with "Read prompts/<file> and do it." Work only on that phase.
- `docs/decisions.md` is the decision record. `docs/solaar-reference.md` has verified facts about Solaar internals (as of the commit it names). `docs/brief.md` is the project overview.
- The planning conversation lives in a claude.ai Project. If a decision changes, update `docs/decisions.md` and this file in the same commit.

## Working rules for Claude Code sessions

- Work only on the phase named in the prompt. Do not start later phases or add features outside v1 scope.
- Stop at the checkpoint the prompt names and show the requested output. Do not continue past it.
- If a design rule below turns out to be wrong or impossible, stop and explain. Do not work around it silently.
- Every .py file starts with `# SPDX-License-Identifier: GPL-2.0-or-later`.
- Before claiming something about Solaar's behavior, check it in Solaar's source (the pinned checkouts under `.solaar/` once Phase 1a exists), not from memory.
- `make test` and `make lint` must pass before you report a phase done.
- No AI attribution anywhere: no Co-Authored-By or similar trailers in commits, no "Generated with" lines in PRs, no AI credits in files. The only author and contributor is rtk94.

## Settled inputs

- Standalone app plus a small upstream PR to Solaar adding a `reload-rules` remote command. Until a user's Solaar has it, Heliostat restarts Solaar after save.
- License GPL-2.0-or-later.
- Rules model: Heliostat owns a typed model of `rules.yaml`. Conformance tests prove every supported Solaar version (1.1.14 and 1.1.20) loads Heliostat's output as the rules Heliostat holds, and that Heliostat's formatting matches Solaar's own save except for the documented deviations (see "Key design rules"). Heliostat does not import Solaar at runtime.
- UI: Qt 6 via PySide6 (Widgets, not QML).
- Device data: shell out to the `solaar` CLI (`show`, `config`) and parse the text. Live button capture is out of v1.
- Packaging: pip-installable `pyproject.toml` project, installed with pipx or a venv. Debian packaging later; Flatpak deferred.
- Target: Debian 13 (Solaar 1.1.14, Python 3.13), KDE Plasma. Must also work against Solaar 1.1.20. The dev machine runs Solaar 1.1.14 (Debian package).

## v1 scope

In:
1. Load, display, edit, and save every rule `rules.yaml` can hold, with no loss. Rules too complex for the simple editor stay editable in an advanced tree view, and are never dropped or rewritten.
2. Simple ("plain-language") editor for the common shape: trigger (Key or MouseGesture), optional Modifiers / Device / Process conditions, then one or more actions.
3. Diversion awareness: flag rules that target a control which isn't diverted, and offer a one-click divert through `solaar config`.
4. Lint and conflict detection: duplicate bindings, rules that can never fire, unknown key names (the 1.1.15 renames), risky actions.
5. Safe save: atomic write, rolling backups, and detection of edits made outside Heliostat (for example by Solaar's own editor).
6. Apply = save + get Solaar to reload (restart fallback now, remote command once upstream lands).
7. A `heliostat lint` CLI.

Out of v1 (deferred, not rejected): live button capture, dry-run / rule simulation, presets, comment preservation in `rules.yaml` (Solaar's own save drops comments too), Wayland focus work beyond what Solaar already supports, Debian/Flatpak packaging.

## Architecture

```
src/heliostat/
  model/        typed rule components, parse from / serialize to PyYAML structures
  rulesfile/    read, atomic write, backups, external-change detection
  solaar/       SolaarClient protocol; CLI-backed impl; parsers; FakeSolaar for tests
  analysis/     lint rules -> Problem objects (severity, rule path, message, fix hint)
  simple/       recognize "simple" rules and generate them (round-trip guaranteed)
  ui/           PySide6 app: device sidebar, rule list, simple editor, advanced tree, problems panel
  cli.py        `heliostat` (GUI) and `heliostat lint <file>`
tests/
  fixtures/     rules corpora, captured `solaar show` / `solaar config` output per version
  conformance/  harness that runs pinned Solaar checkouts in subprocesses
tools/
  fetch_solaar.sh   clones Solaar at pinned tags into .solaar/<tag>/ for conformance
```

## Key design rules

- Model fidelity first. Parse with `yaml.safe_load_all` (the same loader Solaar uses) into typed components. Anything Heliostat doesn't recognize becomes a `Raw` component that serializes back unchanged. Keep scalar types exactly as loaded: a device serial like `12345678` loads as an int and must not be "fixed" into a string.
- Semantic conformance is the hard rule. Every supported Solaar version (1.1.14, 1.1.20) must load Heliostat's output as exactly the rules Heliostat holds. Heliostat never introduces a form that any supported version loads differently from another.
- Serialize like Solaar, with documented deviations. Mirror `diversion._save_config_rule_file`: `%YAML 1.3` header line when there are rules, `explicit_start` and `explicit_end`, `default_flow_style=False`, scalar-only lists in flow style, and single-scalar lists collapsed to the scalar. Output matches Solaar's own save byte-for-byte except for these deviations (each one recorded in `docs/decisions.md` with its reason):
  - D1, Feature names: a Feature argument is written exactly as loaded (`THUMB_WHEEL` or `THUMB WHEEL`), and Feature conditions Heliostat creates use underscores. Reason: Solaar's save writes the spaced form, which Solaar 1.1.14 cannot load (it becomes `None`; fixed in 1.1.15).
  - D2, Argument shapes: every component argument is written in the shape it was loaded (shorthand such as `KeyPress: X`, scalar vs one-item list, invalid or out-of-range values), never rewritten to Solaar's canonical shape or fallback. Components Heliostat creates use Solaar's canonical shapes, so files Solaar saved and rules Heliostat builds still match Solaar's save byte-for-byte (modulo D1). Reason: Solaar's save rewrites shapes, replaces invalid arguments with fallbacks that can delete actions, and collapses one-item lists in ways that change meaning or produce files it cannot reload.
- Existing problems are flagged, never silently fixed. If a loaded file already contains a form some supported Solaar misloads (a spaced Feature name, `Feature: None`), Heliostat preserves it on save and lint reports it with an explicit fix.
- Broken YAML is read-only. If `rules.yaml` fails to parse anywhere, Heliostat refuses to edit or save it, reports the error location, and warns that Solaar is running only the rules before the error and will drop the rest on its next save.
- No Solaar import at runtime. Solaar code only runs inside the conformance harness, in a subprocess with `XDG_CONFIG_HOME` pointed at a temp dir (the `diversion` module loads the user's rules file at import time).
- One seam to Solaar. All CLI calls go through `SolaarClient`, so the GUI and lint layers test against `FakeSolaar`.
- CLI text parsing is fragile. Parsers are built from captured real output, kept as fixtures per Solaar version. Unknown output fails loudly with the raw text attached; it never guesses.
- Never write to the user's real `~/.config/solaar/rules.yaml` or restart the user's real Solaar from automated tests.

## Commands

- `make venv` creates `.venv` (Python 3.13) and installs `-e ".[dev]"`.
- `make test`, `make lint`, `make fmt`, `make conformance` (slow; pinned Solaar versions).
