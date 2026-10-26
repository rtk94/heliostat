# Phase 7: One-click diversion fixes

Read CLAUDE.md first. Precondition: Phase 6 committed.

1. For HL001 problems, offer a fix in the problems panel: "Divert <control> on <device>" (or "Set <control> to Mouse Gestures" where the rule is a MouseGesture). Implement via `SolaarClient.set_divert`.
2. Always confirm with the user before writing to the device. Show the exact `solaar config` command that will run.
3. Re-run analysis after the fix and show whether it took effect.
4. In the simple editor's trigger picker, mark each control as diverted / divertable / not divertable.

Tests with FakeSolaar only. Do not run `solaar config` with a value yourself.

Checkpoint. Stop and show me:
- `make test` and `make lint` output
- the manual test steps for me: un-divert a button in Solaar, see Heliostat flag it, fix it from Heliostat, confirm in Solaar's main window
