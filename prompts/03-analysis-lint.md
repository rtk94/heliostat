# Phase 3: Analysis and `heliostat lint`

Read CLAUDE.md first. Precondition: Phase 2 committed.

Build `src/heliostat/analysis/` and the `heliostat lint [PATH]` subcommand (PATH defaults to `~/.config/solaar/rules.yaml`; read-only; exit code 1 if any error-severity problem).

`Problem = (severity, rule_path, code, message, fix: optional)`. Checks:
- HL001 undiverted-control: a rule triggers on a Key / KeyIsDown / MouseGesture control that SolaarClient reports as not diverted (or not in the right mode, e.g. Mouse Gestures). Skipped with a note if Solaar data is unavailable.
- HL002 unknown-control: control name not known for any connected device (catches the 1.1.15 renames, which Solaar silently turns into key 0).
- HL003 duplicate-binding: two top-level rules with identical trigger and condition set.
- HL004 unreachable: a rule can never run because an earlier top-level rule with a subset of its conditions always ends in an action (Solaar stops processing after an action). Be conservative: only flag cases you can prove; document what is not covered.
- HL005 depress-without-release: KeyPress / MouseClick with `depress` and no matching `release` in the same rule.
- HL006 wayland-process: Process / MouseProcess condition while `XDG_SESSION_TYPE=wayland` and the desktop is not GNOME.

Verify every semantic claim (evaluation order, when processing stops) against `.solaar/1.1.14/lib/logitech_receiver/diversion.py`.

Unit tests per check using `FakeSolaar`, including fixtures that must NOT trigger each check.

Checkpoint. Stop and show me:
- `make test` and `make lint` output
- `heliostat lint` run against every file in `tests/fixtures/rules/` (with FakeSolaar data where needed)
- the exact command for me to run against my real rules file and devices
