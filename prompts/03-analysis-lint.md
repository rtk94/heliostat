# Phase 3: Analysis and `heliostat lint`

Read CLAUDE.md first. Precondition: Phase 2 committed.

Build `src/heliostat/analysis/` and the `heliostat lint [PATH]` subcommand (PATH defaults to `~/.config/solaar/rules.yaml`; read-only; exit code 1 if any error-severity problem).

`Problem = (severity, rule_path, code, message, fix: optional)`. Checks:
- HL000 parse-error: `rulesfile.load` raised `RulesParseError`. Report the line/column, say how many rules Solaar is actually running (the documents before the error), and that Solaar's next save will drop the rest. Error severity. No other checks run on that file.
- HL001 undiverted-control: a rule triggers on a Key / KeyIsDown / MouseGesture control that SolaarClient reports as not diverted (or not in the right mode, e.g. Mouse Gestures). Skipped with a note if Solaar data is unavailable.
- HL002 unknown-control: control name not known for any connected device (catches the 1.1.15 renames, which Solaar silently turns into key 0).
- HL003 duplicate-binding: two top-level rules with identical trigger and condition set.
- HL004 unreachable: a rule can never run because an earlier top-level rule with a subset of its conditions always ends in an action (Solaar stops processing after an action). Be conservative: only flag cases you can prove; document what is not covered.
- HL005 depress-without-release: KeyPress / MouseClick with `depress` and no matching `release` in the same rule.
- HL006 wayland-process: Process / MouseProcess condition while `XDG_SESSION_TYPE=wayland` and the desktop is not GNOME.
- HL007 spaced-feature-name: a Feature argument containing a space (e.g. `THUMB WHEEL`). Error if the installed Solaar is older than 1.1.15 (that version loads it as `None`, so the rule never matches); warning otherwise (it breaks if the file is used with Solaar 1.1.14). Fix: replace spaces with underscores in that argument only.
- HL008 lost-feature: a Feature argument that is literally `None`. Error: the feature name was already lost (most likely Solaar 1.1.14 saving a spaced name twice), so the rule never matches. No automatic fix; the message tells the user to pick the feature again.
- HL009 load-abort: valid YAML that aborts Solaar's load (e.g. `Feature: [CROWN]`, `Rule: 5`, a null document, `Test: mouse-up`). The file stays editable in Heliostat. Error: Solaar stops loading at that rule, and its next save drops everything after it.
- HL010 solaar-save-hazard: a rule contains a form Solaar's own save would damage: a one-item-list collapse that changes meaning or makes the file unloadable, an invalid argument Solaar replaces with a data-deleting fallback, or an unknown component that makes Solaar's save fail. Warning. Confirm each HL010 case against the pinned Solaar source (`.solaar/1.1.14/` and `.solaar/1.1.20/`), and with the conformance harness where it can show it, before it ships; `tests/fixtures/rules/collapse-hazards.yaml` and `malformed-args.yaml` hold the known cases.

Fixes are offered, never applied by `lint`. Verify every semantic claim (evaluation order, when processing stops, how Feature names load per version) against `.solaar/1.1.14/lib/logitech_receiver/diversion.py` and `.solaar/1.1.20/...`.

Unit tests per check using `FakeSolaar`, including fixtures that must NOT trigger each check. Reuse `tests/fixtures/rules/feature-names.yaml` and `solaar-docs-example.yaml` where they fit.

Checkpoint. Stop and show me:
- `make test` and `make lint` output
- `heliostat lint` run against every file in `tests/fixtures/rules/` (with FakeSolaar data where needed)
- the exact command for me to run against my real rules file and devices
