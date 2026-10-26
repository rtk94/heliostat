# Phase 5: Read-only Qt shell

Read CLAUDE.md first. Precondition: Phase 4 committed.

Build a read-only PySide6 GUI in `src/heliostat/ui/`. Qt Widgets only. Running `heliostat` with no arguments opens it; existing subcommands keep working.

Main window:
- Left: device sidebar from SolaarClient. Degrade gracefully if Solaar is missing or not running (show why, keep the rest usable).
- Center: list of top-level rules, showing `describe()` for simple rules and a compact one-line form for the rest.
- Right: the selected rule as a tree (advanced view, read-only in this phase).
- Bottom: problems panel from the analysis layer. Clicking a problem selects its rule.

Run slow SolaarClient calls off the GUI thread (QThreadPool or similar). The window must open immediately using the rules file alone, then fill in device data.

pytest-qt smoke tests with FakeSolaar: window opens, rules listed, selecting a problem selects its rule. Tests must run headless (QT_QPA_PLATFORM=offscreen).

Checkpoint. Stop and show me:
- `make test` and `make lint` output
- the exact command for me to launch it against my real rules file (I will take the screenshot)
