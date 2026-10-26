# Phase 4: Simple-rule mapping

Read CLAUDE.md first. Precondition: Phase 3 committed.

Build `src/heliostat/simple/`.

A SimpleRule is: a trigger (Key with pressed / released / any, or a MouseGesture sequence), optional Device, optional Modifiers, optional Process, then 1..N actions from {KeyPress, MouseClick, MouseScroll, Execute, Set}.

- `recognize(component) -> SimpleRule | None`. Returns None for anything outside the shape; those rules go to the advanced editor.
- `generate(SimpleRule) -> Rule` component in the model.
- `describe(SimpleRule) -> str`: a one-line English summary, e.g. "When Back Button on MX Master 3 is pressed: press Ctrl+Tab".

Invariant (hypothesis property test): for every Rule r where `recognize(r)` is not None, `generate(recognize(r))` serializes byte-identically to r. Never normalize a user's rule just because it was opened in the simple editor.

Also report, across all fixtures in `tests/fixtures/rules/`, what fraction of top-level rules are recognized as simple, and list the shapes of the ones that are not.

Checkpoint. Stop and show me:
- `make test` and `make lint` output
- the recognition stats and the list of unrecognized shapes
- `describe()` output for every recognized rule in the fixtures
