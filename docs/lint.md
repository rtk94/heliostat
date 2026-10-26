# Lint checks

`heliostat lint [PATH]` checks a Solaar rules file (default `$XDG_CONFIG_HOME/solaar/rules.yaml`). It only
reads: the file, `solaar --version`, and `solaar show`. Fixes are offered, never applied. Exit status 0 if
there are no errors, 1 if there are, 2 if the file cannot be read. With no PATH and no rules file at the
default path, it says Solaar has no user rules and exits 0.

```
heliostat lint                          # your rules, your Solaar, your connected devices
heliostat lint FILE --no-solaar         # no device checks; add --solaar-version X.Y.Z to fix the version
heliostat lint FILE --solaar-show SHOW.txt [--solaar-version X.Y.Z]   # devices from saved `solaar show` output
```

Each problem has a severity (error, warning, or note for a check that could not run), a rule path, a code,
a message, and an optional fix: a `solaar config` command, or a replacement component.

Behavior claims come from `.solaar/1.1.14/` and `.solaar/1.1.20/` `lib/logitech_receiver/diversion.py` (see
`docs/solaar-reference.md`, "Evaluation details for lint"). The ones the conformance harness can show are
tested against real Solaar in `tests/conformance/test_lint_claims.py`: which documents abort the load
(HL009), what Solaar's save damages (HL010), and where processing stops (HL003, HL004, HL006).

**Versions.** Lint uses the installed Solaar's version. 1.1.14 and earlier use 1.1.14's names and behavior;
1.1.15 and later use 1.1.20's. Only 1.1.14 and 1.1.20 are checked against source, so for any other version
the version-dependent findings (HL002 names) are warnings that say which version's names were used. When the
version is unknown, every supported version is considered.

## Checks

| Code | Name | Severity | What |
|---|---|---|---|
| HL000 | parse-error | error | The file is not valid YAML. Reports line and column, how many rules Solaar is running (the documents before the error), and that Solaar's next save drops the rest. No other check runs. |
| HL001 | undiverted-control | error | A Key, KeyIsDown or MouseGesture names a control that is not diverted on any connected device that has it (Regular mode), or for MouseGesture, not in Mouse Gestures mode. Fix: the `solaar config <serial> divert-keys <control> <mode>` command. |
| HL002 | unknown-control | error / warning | A control name Solaar does not resolve (error: the condition never matches; Solaar loads it as key 0), or that no connected device has (warning). Suggests the other version's name for renamed controls, the exact-case name, or for MouseGesture the printed name. |
| HL003 | duplicate-binding | warning | Two top-level rules with the same trigger (Key or MouseGesture) and the same set of leading conditions. Says when the first one always stops processing, so the second never runs. |
| HL004 | unreachable | warning | A top-level rule that can never run: an earlier rule has a subset of its leading conditions and always ends in an action. |
| HL005 | depress-without-release | warning | KeyPress or MouseClick with `depress`, and no `release` of the same key or button anywhere in the same top-level rule. |
| HL006 | wayland-process | error | Process or MouseProcess on Wayland outside GNOME. Solaar cannot read the focused window there: the condition returns None, which stops this rule and every later rule (built-in rules too) each time it is reached. |
| HL007 | spaced-feature-name | error / warning | A Feature argument with a space (`THUMB WHEEL`). Error if the installed Solaar is older than 1.1.15 (it loads it as None, so the rule never matches), warning otherwise. Fix: underscores in that argument. |
| HL008 | lost-feature | error | `Feature: None`: the name is already lost, the rule never matches. No automatic fix. |
| HL009 | load-abort | error / warning | Valid YAML that makes Solaar's load raise. Solaar runs only the rules before it; its next save drops it and everything after. Warning when only a supported version other than the installed one aborts (e.g. `Feature: 5` aborts on 1.1.15+, not on 1.1.14). |
| HL010 | solaar-save-hazard | warning | A form Solaar's own save (its rule editor) would damage. Cases below. |

### Details

**HL001.** Controls are matched by Solaar's printed name against `solaar show`'s control list. Key and
KeyIsDown need the control diverted in any non-Regular mode: in Mouse Gestures and Sliding DPI the control
is still diverted at the device and its key notifications still reach the rules. MouseGesture needs the
initiating control (the first item, if it is not a movement) to have Mouse Gestures as the mode Solaar
saved; without an initiating control, any control in Mouse Gestures mode will do. Only devices that a
top-level `Device` condition (before the first action) allows are considered. Not reported: names under a
`Not`; G1-G32, M1-M8 and MR (they come from other HID++ features); controls no connected device has (HL002);
a control whose live mode is diverted but whose saved mode is unknown (the CLI cannot tell gesture modes
apart, docs/decisions.md 2026-10-26).

**HL002.** Name lookup mirrors Solaar: `Key` accepts the underscore key (`Back_Button`) or the printed name
(`Back Button`) exactly, and `unknown:XXXX` by number; a case mismatch passes Solaar's membership test but
looks up None. `KeyIsDown` has no `unknown:` lookup (an `unknown:` name there is not reported, since it only
resolves if Solaar created the name earlier). `MouseGesture` compares printed names exactly, so
`Back_Button` never matches there. Solaar 1.1.15 renamed 16 controls, and three names (`Volume Up`,
`Volume Down`, `Play/Pause`) moved to a different control; HL002 reports both directions with a fix.

**HL003, HL004.** A rule's leading conditions are its typed conditions before its first action, sub-rule
or unknown component. Conditions compare by value (Key names resolved to control numbers, a missing Key
action counted as `pressed`, Modifiers as a set of known names). A rule "always ends in an action" when its
remaining components are only actions and sub-rules, the last one an action. HL004 only uses an earlier
rule whose leading conditions give the same result wherever they are evaluated in one pass: Key,
MouseGesture, Feature, Report, Test (not `thumb_wheel_up`/`down` with a parameter, which change Solaar
state), TestBytes, Device, Host, and Not / Or / And of those. Modifiers also count when no rule between the
two has an action (a KeyPress could change the modifier state). Not covered, so never reported: earlier
rules with Process, MouseProcess, KeyIsDown, Setting or Active conditions, rules that stop processing
through a condition that returns None, unknown components, conditions after the first action, and rules
that can never fire for other reasons (two different Key conditions, for example).

**HL005.** Keys and buttons are matched by exact name. The order of depress and release within the rule
is not checked.

**HL006.** Solaar decides it is on Wayland from `WAYLAND_DISPLAY` in its own environment; lint checks
`XDG_SESSION_TYPE=wayland` or `WAYLAND_DISPLAY` in its own. GNOME is detected from `XDG_CURRENT_DESKTOP`;
on GNOME, Process works only with Solaar's GNOME extension, which lint does not check.

**HL009.** Mirrors the argument handling of every component constructor (an unhashable Feature name, a
non-list Rule/Or/And/Modifiers/MouseGesture/Execute argument, MouseScroll and MouseClick arguments without
a length, KeyPress keys that are not names, an `unknown:` Key name without 4 hex digits, the deprecated
`mouse-*` Test names, null or scalar documents, ...). A Later with an invalid delay compiles nothing inside
it, so nothing inside it aborts. The conformance test runs the predictor and real Solaar on 77 documents, aborting and not.

**HL010.** Reported cases, each confirmed with the conformance harness:

- A one-item list collapsed in a way that changes meaning: inside Device, Active, Host, Set, Setting,
  a Test parameter, or nested in an Execute command; `Execute: [<number>]` (its next load aborts);
  `TestBytes: [n]` and `Test: [n]` (its next save fails).
- A fallback that deletes content: Later with an invalid delay and components inside (saved as `Later: 0`);
  Set / Setting with fewer than 3 items (saved as `[]`); a Key / KeyIsDown name Solaar does not know (saved
  as `'0'` or `'None'`); a Feature name Solaar does not know (saved as `None`).
- On Solaar 1.1.14, a multi-word Feature name with underscores: its save writes the spaced form, which 1.1.14
  then loads as None.
- Solaar's save fails outright: an unknown or malformed component (Solaar compiles it to an empty condition
  with no saved form), `TestBytes` that is not a list, `Execute` that is a mapping.

Not reported: invalid words in fixed vocabularies that Solaar already ignores at load and rewrites on save
(unknown Test names saved as `False`, unknown MouseClick buttons saved as `null`, unknown modifiers dropped,
an invalid Key action saved as `pressed`, `Report` saved as `-1`, an invalid MouseScroll saved as `[0, 0]`).
The rule works the same before and after, though the original text is gone.
