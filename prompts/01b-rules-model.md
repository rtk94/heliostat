# Phase 1b: Rules model and YAML I/O

Read CLAUDE.md first. Precondition: Phase 1a is committed and `make conformance` passes. If not, stop and tell me.

1. `src/heliostat/model/`: typed dataclasses for all 24 component types plus `Raw` (an unknown or malformed component, kept verbatim). Each has `from_yaml(obj)` and `to_yaml()`. Preserve scalar types exactly as loaded. Preserve argument forms that Solaar accepts in more than one shape (for example Key as `"Name"` vs `["Name", "pressed"]`) so output matches input. A top-level `RuleSet` holds the list of user rules.

2. `src/heliostat/rulesfile/`: `load(path) -> RuleSet` (using `yaml.safe_load_all`) and `dumps(RuleSet) -> str`, reproducing Solaar's `_save_config_rule_file` formatting byte-for-byte. Read `.solaar/1.1.14/lib/logitech_receiver/diversion.py` and `.solaar/1.1.20/...` for the exact behavior. Writing to disk safely is Phase 6; this phase only needs `dumps`.

3. Tests:
   - Unit tests (plain `make test`): each component type parses and serializes; Raw passthrough (a file with an unknown component type survives load/dumps unchanged); scalar types preserved.
   - Conformance (`make conformance`): for every fixture in `tests/fixtures/rules/`, `heliostat.dumps(load(f))` is byte-identical to Solaar's `roundtrip(f)` output, under 1.1.14 AND 1.1.20.
   - Conformance property test with hypothesis: generate random valid rule trees, dump with Heliostat, feed to `solaar_runner dump-data`, and compare with Heliostat's own structure. Keep example counts modest so the run stays under a couple of minutes.

4. If byte-identical output turns out to depend on the PyYAML version, stop and report it rather than loosening the test.

Checkpoint. Stop and show me:
- `make test`, `make lint`, and `make conformance` output
- any case where 1.1.14 and 1.1.20 behaved differently
- anything in Solaar's load/save behavior that surprised you
