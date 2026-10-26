# Phase 6: Editing, save, and apply

Read CLAUDE.md first. Precondition: Phase 5 committed.

1. Simple editor form for SimpleRule: trigger picker (controls from SolaarClient for the chosen device, with a free-text fallback), modifiers, optional process, action list with add / remove / reorder. Live `describe()` preview.
2. Advanced tree editor: add / remove / reorder / edit any component, including Raw (edited as YAML text, validated on commit).
3. Rule list: add, delete, duplicate, reorder (order matters: evaluation is sequential).
4. Undo / redo via QUndoStack for all edits.
5. Save in `src/heliostat/rulesfile/`: atomic write (temp file + rename in the same directory), keep the last 10 backups as `rules.yaml.heliostat-bak.<timestamp>`, refuse to overwrite if the file changed on disk since load (show a diff and offer reload or overwrite).
6. Apply = Save + `SolaarClient.reload_rules()`, with the ReloadResult shown in the status bar.
7. The problems panel re-runs analysis after edits (debounced).

pytest-qt tests (FakeSolaar, temp dirs only, never the real config): edit then save produces the expected YAML; external-change detection; undo / redo; a Raw component survives an edit to a sibling; backups rotate at 10.

Checkpoint. Stop and show me:
- `make test`, `make lint`, and `make conformance` output (saved files must still be byte-identical to Solaar's own save)
- the manual test steps you recommend I run on my real setup
