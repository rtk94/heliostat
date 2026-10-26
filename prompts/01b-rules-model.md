# Phase 1b: Rules model and YAML I/O

Read CLAUDE.md first, especially "Key design rules" (semantic conformance, deviation D1, broken YAML). Precondition: Phase 1a is committed and `make conformance` passes. If not, stop and tell me.

1. `src/heliostat/model/`: typed dataclasses for all 24 component types plus `Raw` (an unknown or malformed component, kept verbatim). Each has `from_yaml(obj)` and `to_yaml()`. Preserve scalar types exactly as loaded. Preserve argument forms that Solaar accepts in more than one shape (for example Key as `"Name"` vs `["Name", "pressed"]`) so output matches input. A top-level `RuleSet` holds the list of user rules.
   - Feature (deviation D1): store the argument string exactly as loaded, including `THUMB WHEEL`, `THUMB_WHEEL`, and the literal `None`. A constructor for new Feature conditions (used by later phases) writes the underscore form. Add a small helper that reports whether a Feature argument is spaced or `None`, for Phase 3 lint.

2. `src/heliostat/rulesfile/`:
   - `load(path) -> RuleSet` using `yaml.safe_load_all`. Parsing is strict: if any document fails to parse, raise `RulesParseError` carrying the line/column and the number of documents that parsed before the error (that is how many rules Solaar is actually running). Never return a partial RuleSet.
   - `dumps(RuleSet) -> str`, reproducing Solaar's `_save_config_rule_file` formatting. Read `.solaar/1.1.14/lib/logitech_receiver/diversion.py` and `.solaar/1.1.20/...` for exact behavior. Writing to disk safely is Phase 6; this phase only needs `dumps`.

3. Tests:
   - Unit tests (plain `make test`): each component type parses and serializes; Raw passthrough (a file with an unknown component type survives load/dumps unchanged); scalar types preserved; Feature arguments preserved in all three forms; `RulesParseError` on `solaar-docs-example.yaml` (the broken one) with the right line and a parsed-document count of 3.
   - Conformance, semantic (`make conformance`, the hard rule): for every fixture that parses, and for each of 1.1.14 and 1.1.20, `solaar_runner dump-data` on Heliostat's `dumps` output equals `dump-data` on the original file. Where a fixture contains a form some version misloads (spaced Feature, `Feature: None`), assert Heliostat's output loads the same way as the original on that version (Heliostat must not make it better or worse), and note the reason in the test.
   - Conformance, formatting: Heliostat's `dumps` output equals Solaar's `roundtrip` output byte-for-byte, after a comparison helper that applies only the documented deviations (D1: treat a Feature argument's spaces and underscores as equal). Keep the deviation list in one place in the test code with a comment pointing at docs/decisions.md.
   - Conformance property test with hypothesis: generate random valid rule trees (new Feature conditions in underscore form), dump with Heliostat, feed to `solaar_runner dump-data` under both versions, and compare with Heliostat's own structure. Keep example counts modest so the run stays under a couple of minutes.

4. If any other difference between Heliostat output and Solaar's save shows up that is not covered by D1, stop and report it. Do not add a deviation yourself; deviations are decisions.

Checkpoint. Stop and show me:
- `make test`, `make lint`, and `make conformance` output
- any case where 1.1.14 and 1.1.20 behaved differently, beyond the known Feature-name bug
- anything in Solaar's load/save behavior that surprised you
