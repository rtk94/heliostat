# Phase 1a: Conformance harness

Read CLAUDE.md first. This phase builds the harness that runs real Solaar code against rules files. No Heliostat model code yet.

1. `tools/fetch_solaar.sh`: shallow-clone https://github.com/pwr-Solaar/Solaar at tags `1.1.14` and `1.1.20` into `.solaar/<tag>/` (already gitignored). Idempotent: skip a tag that is already checked out at the right commit.

2. `tests/conformance/solaar_runner.py`: a script meant to be run as a SUBPROCESS with `PYTHONPATH=.solaar/<tag>/lib` and `XDG_CONFIG_HOME` set to a fresh temp dir (Solaar's `diversion` module loads the user's rules file at import time; it must never see the real one). Subcommands:
   - `roundtrip <in.yaml> <out.yaml>`: load with `diversion._load_rule_config(in)`, set `diversion.rules` to the result, save with `diversion._save_config_rule_file(out)`.
   - `dump-data <in.yaml>`: print JSON of `[r.data() for r in <user rules>]`.

   Interpreter: importing `logitech_receiver.diversion` needs PyGObject (Gdk, GLib), psutil, PyYAML, python-xlib, and optionally evdev. This machine has the Debian `solaar` package installed, so the system interpreter `/usr/bin/python3` probably already has all of them. Check that first and prefer it over installing anything. Do not add Solaar's dependencies to Heliostat's own venv or pyproject. Make the interpreter configurable (env var `HELIOSTAT_SOLAAR_PYTHON`, default `/usr/bin/python3`). Record in `tests/conformance/README.md` exactly what was needed and whether a display was required.

3. `tests/fixtures/rules/`:
   - `solaar-docs-example.yaml`: the example rule file from https://pwr-solaar.github.io/Solaar/rules (fetch it; do not reconstruct it from memory).
   - `all-components.yaml`: a synthetic file using each of the 24 component types at least once (Rule, Not, Or, And, Process, MouseProcess, Feature, Report, Setting, Modifiers, Key, KeyIsDown, Test, TestBytes, MouseGesture, Active, Device, Host, KeyPress, MouseScroll, MouseClick, Set, Execute, Later), including nested Rules, both Key argument forms (`Name` and `[Name, pressed]`), and an all-digit device serial.
   - Check every argument shape against `.solaar/1.1.14/lib/logitech_receiver/diversion.py`, not memory.

4. `tests/conformance/test_solaar_fixed_point.py`, marked `@pytest.mark.conformance`: for each tag and each fixture, run `roundtrip` twice and assert the second output is byte-identical to the first (Solaar's own output is a fixed point). Skip with a clear message if `.solaar/<tag>` is missing.

5. Makefile: `conformance` target runs `tools/fetch_solaar.sh` then `pytest -m conformance`.

Checkpoint. Stop and show me:
- `tools/fetch_solaar.sh` output
- the contents of `tests/conformance/README.md`
- `make test`, `make lint`, and `make conformance` output
- any fixture that Solaar 1.1.14 and 1.1.20 serialize differently
