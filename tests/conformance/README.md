# Conformance harness

Runs real Solaar rule load/save code against rules files, so Heliostat's own model and serializer can be
checked against what Solaar actually does. Solaar is never imported into Heliostat's process or venv.

```
make conformance          # tools/fetch_solaar.sh, then pytest -m conformance
```

## Pieces

- `tools/fetch_solaar.sh` shallow-clones https://github.com/pwr-Solaar/Solaar at the pinned tags
  (`1.1.14`, `1.1.20`) into `.solaar/<tag>/`. It skips a tag that is already checked out, clean, at the
  commit the tag points to, and re-clones otherwise.
- `solaar_runner.py` is run as a subprocess, never imported. Subcommands:
  - `roundtrip <in.yaml> <out.yaml>`: `diversion._load_rule_config`, set `diversion.rules`, then
    `diversion._save_config_rule_file`.
  - `dump-data <in.yaml>`: JSON of `[r.data() for r in <user rules>]`.

  Exit 0 on success, 1 if Solaar logged any ERROR (Solaar catches load and save exceptions and only logs
  them, so this is the only way to notice a partial load), 2 on bad usage or an unsafe environment. It
  refuses to run if `XDG_CONFIG_HOME` is unset, is the real `~/.config`, or already holds
  `solaar/rules.yaml`, and it checks that `logitech_receiver.diversion` came from `PYTHONPATH`.
- `harness.py` builds the subprocess environment (`run_runner`, `solaar_roundtrip`) for tests.
- `test_solaar_fixed_point.py`: for each tag and each `tests/fixtures/rules/*.yaml`, round-trip twice and
  require the second output to be byte-identical to the first.

### How `roundtrip` loads and saves

`_save_config_rule_file(name)` saves only the rules whose `source == name`, and `_load_rule_config(path)`
sets `source` to the path it loaded from. Loading `in.yaml` and saving to `out.yaml` would therefore write
an empty file. Solaar itself always loads and saves the same path, so `roundtrip` copies `in.yaml` to
`out.yaml` first and then loads and saves `out.yaml`.

## Interpreter and dependencies

The runner uses `HELIOSTAT_SOLAAR_PYTHON`, default `/usr/bin/python3`. On the dev machine (Debian 13,
`solaar 1.1.14-4` installed) nothing extra had to be installed. The system interpreter (Python 3.13.5)
already has everything, all from Debian packages that the `solaar` package pulls in:

| Module | Debian package | Version | Needed by |
|---|---|---|---|
| `gi` (Gdk 3.0, GLib) | `python3-gi`, `gir1.2-gtk-3.0` | 3.50.0-4+b1, 3.24.49-3 | `diversion` import |
| `psutil` | `python3-psutil` | 7.0.0-2 | `diversion` import |
| `yaml` | `python3-yaml` | 6.0.2-1+b2 | `diversion` import |
| `Xlib` | `python3-xlib` | 0.33-3 | optional in `diversion`, imported if present |
| `evdev` | `python3-evdev` | 1.9.1-1 | optional; without it `MouseClick` knows no buttons |
| `pyudev` | `python3-pyudev` | 0.24.3-1 | 1.1.20 only, via Solaar's bundled `hidapi` |

`keysyms` and `hidapi` come from the Solaar checkout's own `lib/`. Debian's installed copy of Solaar lives
in `/usr/share/solaar/lib`, which is not on `sys.path`, so only the pinned checkout is imported.

None of these go into Heliostat's venv or `pyproject.toml`.

Interpreter flags: `-s` (no user site-packages). `-I` and `-E` cannot be used because they ignore
`PYTHONPATH`.

## Display

**No display is required.** The harness runs the runner with a minimal environment: `PATH`, `LANG=C.UTF-8`,
`HOME` and `XDG_CONFIG_HOME` pointed at a fresh temp dir, `PYTHONPATH=.solaar/<tag>/lib`. `DISPLAY`,
`WAYLAND_DISPLAY` and the D-Bus session address are deliberately dropped. Under those conditions:

- `Gdk.Display.get_default()` returns `None` and `diversion` sets `gkeymap = None`; the import succeeds.
- Constructing a `Process` or `MouseProcess` condition calls `x11_setup()`, which fails and logs a WARNING
  with a traceback ("X11 not available"). That is noise, not failure: the rule still loads and saves.
- `Device: 12345678` logs "rule Device argument not a string"; the int is kept and saved as an int.

Dropping `DISPLAY` also keeps the runner from connecting to the user's X server. Warnings go to the
runner's stderr. Only ERRORs make it exit non-zero.

## Fixtures (`tests/fixtures/rules/`)

- `solaar-docs-example.yaml`: the "Example Solaar Rule File" from https://pwr-solaar.github.io/Solaar/rules,
  fetched 2026-10-25 and kept verbatim. It is **not valid multi-document YAML**: there is no `---`
  between the `...` that ends the third rule and `- Feature: CROWN`. PyYAML raises a `ParserError`
  after three documents, and Solaar logs the error and silently keeps the first 3 of the 6 rules. The
  same text is in `docs/rules.md` at both pinned tags. Strict xfail on both tags.
- `solaar-docs-example-fixed.yaml`: the same file with only that one `---` added.
- `all-components.yaml`: synthetic. Uses all 24 component types, nested `Rule`s, both `Key` forms, single-item
  lists that Solaar collapses to scalars, `null` in `Set`/`Setting` lists (which forces block style), and
  an all-digit device serial. Argument shapes were checked against
  `.solaar/1.1.14/lib/logitech_receiver/diversion.py`. Control names are ones present in both tags'
  `special_keys.CONTROL`.
- `feature-names.yaml`: `Feature` with underscore and space spellings (see below). Strict xfail on 1.1.14.

## Known Solaar behavior the fixtures pin down

- **`Feature` names in 1.1.14.** `Feature.data()` writes `str(SupportedFeature.X)`, which is the enum
  name with `_` replaced by a space (`THUMB WHEEL`). 1.1.14 loads with `SupportedFeature[name]`, which
  accepts only the underscore spelling. 1.1.20 loads `SupportedFeature[name.replace(" ", "_")]`. So in 1.1.14:
  - `THUMB_WHEEL` saves as `THUMB WHEEL`. The next load fails and the save after that writes `None`.
    1.1.14's save is not a fixed point here.
  - The space spelling the docs use (`THUMB WHEEL`, `LOWRES WHEEL`) loads as `None` straight away.
    `solaar-docs-example-fixed.yaml` saves `Feature: None` on 1.1.14 and `Feature: THUMB WHEEL` on 1.1.20.
    This is the only 1.1.14 vs 1.1.20 serialization difference among the current fixtures.
  - One-word names (`CROWN`) are unaffected.
- **Partial load.** On a YAML error partway through the file, `_load_rule_config` keeps the rules parsed
  before the error, logs, and carries on. A Solaar save after that drops the rest of the file.
