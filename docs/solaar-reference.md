# Solaar Reference Notes

Verified against Solaar master at commit `e7304c4` (2026-08-18), version string 1.1.20, plus the published rules docs at https://pwr-solaar.github.io/Solaar/rules. Re-verify before relying on anything here if Solaar has moved on. The dev machine runs the Debian package, `solaar 1.1.14-4`.

## Basics

- Repo: https://github.com/pwr-Solaar/Solaar (Python, GTK 3 via PyGObject).
- Release notes say 1.1.18+ is only guaranteed on Python 3.13 or later.
- 1.1.20 uses uinput for all simulated input, including under X11. Users need write access to `/dev/uinput` (Solaar ships a udev rule in `rules.d/`).
- GUI is a `Gtk.Application` (`APP_ID = "io.github.pwr_solaar.solaar"`) with `HANDLES_COMMAND_LINE` (single instance).
- Activity: Peter F. Patel-Schneider is the primary maintainer (about 70 commits in the 12 months to Aug 2026), Ken Sanislo second (about 59).

## Distribution versions (Debian tracker, checked 2026-10-25)

- oldstable (bookworm): 1.1.8
- stable (trixie, Debian 13): 1.1.14
- testing and unstable: 1.1.20

## Remote command channel (existing IPC)

- A second `solaar` process registers the same `Gtk.Application` ID. If the GUI is already running, `application.get_is_remote()` is true and `application.run([yaml_string])` forwards arguments to the primary instance over the session bus.
- The primary handles them in `lib/solaar/ui/__init__.py::_command_line`: arguments are a YAML-encoded list; no args activates the window; `["config", device, setting, ...]` applies a setting change. Anything else is silently ignored and returns 0.
- `lib/solaar/cli/config.py` uses this: it writes the setting directly to the device, then forwards the same command to the GUI so it stays in sync.
- This is the natural place for a `reload-rules` command.

## License

- `COPYRIGHT` and `LICENSE.txt` state GPL version 2. `setup.py` says "GPLv2".
- 82 of 95 .py files under `lib/` carry "version 2 or (at your option) any later version" headers, including `diversion.py` and `diversion_rules.py`.
- The 13 without that header fall back to the top-level GPL-2.0 notice: `hidapi/*`, `keysyms/*`, `hid_parser/*`, `settings_validator.py`, `centurion_constants.py`, `device_quirks.py`, `rgb_effects_probe.py`, `ui/about/__init__.py`, `custom_logger.py`.

## Where the relevant code lives

- `lib/logitech_receiver/diversion.py` (~1570 lines): rules engine. Rule/condition/action classes, `COMPONENTS` registry, evaluation, uinput simulation, focus lookups, YAML load/save. Imports `gi` (Gdk, GLib), `psutil`, `yaml`, `keysyms`, optionally `evdev`.
- `lib/solaar/ui/diversion_rules.py` (~1890 lines): the GTK3 rule editor.
- `lib/solaar/ui/rule_base.py`, `rule_conditions.py`, `rule_actions.py`: more editor UI pieces.
- `lib/solaar/ui/__init__.py`: application setup and remote command handling.
- `lib/solaar/cli/`: `show`, `probe`, `profiles`, `config`, `pair`, `unpair`.
- `lib/logitech_receiver/special_keys.py`: Logitech control names and IDs.
- `lib/logitech_receiver/settings_templates.py`: setting definitions. Diversion-related setting names: `divert-keys`, `divert-crown`, `divert-gkeys`, `gesture2-divert`, `reprogrammable-keys`, `persistent-remappable-keys`.
- Solaar's own tests (`tests/logitech_receiver/test_diversion.py`) import `diversion` in CI without a display.

## Rules file

- Path: `$XDG_CONFIG_HOME/solaar/rules.yaml`, default `~/.config/solaar/rules.yaml`.
- YAML, zero or more documents, each document one rule. Loaded with `yaml.safe_load_all`.
- Saved by `_save_config_rule_file`: writes `%YAML 1.3` manually when there are rules, then `yaml.dump_all` with `explicit_start`, `explicit_end`, `default_flow_style=False`, `encoding="utf-8"`; scalar-only lists in flow style; single-scalar lists collapsed to the scalar; NamedInt converted to int. Only user rules are saved, not built-ins. Comments are not preserved.
- Built-in rule (Brightness Up/Down to `XF86_MonBrightness*` key taps) runs after user rules.
- The 24 component types and the load/save code are the same in 1.1.14 and 1.1.20.
- 1.1.15 renamed some keys to match Logitech names; rules using removed names silently get key 0.
- `_save_config_rule_file(name)` saves only rules whose `source == name`, and `_load_rule_config` sets `source` to the path it loaded. Solaar always loads and saves the same path; tooling must do the same (Phase 1a finding).
- Feature names (verified 2026-10-26): `Feature.data()` writes `str(SupportedFeature)`, which is the name with spaces (`THUMB WHEEL`). 1.1.14 loads with `SupportedFeature[feature]` (underscores only), so the spaced form becomes `None` and the rule never matches; a second save writes the literal `None`. 1.1.15 to 1.1.20 load with `feature.replace(" ", "_")` and accept both.
- Broken YAML: `safe_load_all` raises partway through; Solaar catches it, logs an error, and keeps the rules parsed before the error. Its next save writes only those, dropping the rest.
- The published rules example (docs/rules.md, both 1.1.14 and 1.1.20) is missing a `---` before `- Feature: CROWN`, so only 3 of its 6 rules load.
- Save rewrites argument shapes, not just formatting (verified 2026-10-26 against both pinned tags). It saves each component's `data()`, which normalizes: `Key: x` / `Key: [x]` -> `[x, pressed]`; `KeyPress: a` / `[a, b]` / `[a, depress]` -> `[[a, ...], action]` (written as a block list); `MouseClick: b` -> `[b, 1]`; `Not: [c]` -> `Not: c`; `MouseScroll: [[x, y]]` -> `[x, y]`; `Test: [t, null]` -> `t`; `Key: Back_Button` -> `Back Button`; `Process: 42` -> `'42'`. Invalid arguments are replaced by the fallback the constructor picked: unknown Key or KeyIsDown name -> `'0'`, unknown modifier dropped, unknown Test name -> `'False'`, non-int Report -> `-1`, out-of-range Later -> `Later: 0` (its actions dropped), bad MouseScroll -> `[0, 0]`, unknown MouseClick button -> `null`.
- Save's `convert()` collapses every one-scalar list, including for components that do not accept the scalar alike: `Device: [x]` (never matches) saves as `Device: x` (matches); `Set: [.., [1600]]` saves the value as `1600`; `TestBytes: [1]` and `Test: [5]` save as `TestBytes: 1` / `5`, which the next save crashes on (`self.test[:]`); `Execute: [5]` saves as `Execute: 5`, which the next load raises on.
- Load aborts on some valid YAML: a component constructor that raises ends `_load_rule_config` the same way a YAML error does (error logged, earlier rules kept, the rest dropped). Seen with `MouseScroll: 5`, `MouseClick: 5`, `Feature: [CROWN]`, `Rule: 5`, `Execute: 5`, `Test: mouse-up` (the deprecated mouse-movement tests index `MOUSE_GESTURE_TESTS[0]` and raise `KeyError`) and an empty (null) document.
- An unknown component type loads as a plain `Condition` (warning only, always false), but `Condition` has no `data()`, so any save of such a file raises `AttributeError` outside the `try` and writes nothing. A document that is a mapping instead of a list does the same.

## Reload behavior

- `diversion.load_config_rule_file()` runs once at module import, and again only when the user hits reload inside Solaar's own rule editor.
- No file watcher. The only IPC is the remote command channel above, which has no reload command.
- Consequence: an external process that writes `rules.yaml` will NOT change live behavior until Solaar restarts or the user reloads from Solaar's editor.

## Evaluation semantics (summary of the docs)

- A rule is a sequence of components: sub-rules, conditions, actions.
- Components evaluate in order. A false condition stops the rule. If the last thing a rule does is execute an action, no further rules are processed for that notification.
- `Or` short-circuits on true; `And` evaluates like a rule; `Not` negates.
- `Device` condition: 1.1.14 matches the device's unit ID or serial; 1.1.20 also matches its codename or name. This is an evaluation-only difference; load, save and `data()` are the same.
- Rules only fire on HID++ notifications. A key, button, wheel, or crown must be diverted first or nothing fires.

## Component types

Conditions: Not, Or, And, Feature, Report, Key (name or `[name, pressed|released]`), KeyIsDown, MouseGesture, Modifiers, Process, MouseProcess, Device, Active, Host, Setting, Test, TestBytes.

Actions: KeyPress (X11 keysym names, optional click/depress/release), MouseScroll, MouseClick, Execute, Set (device setting, `~` toggles booleans), Later (delay 1 to 100 s, then sub-components).

Plus `Rule` (a nested sequence). Process and MouseProcess do not work on Wayland except GNOME with the Solaar GNOME extension.

## Useful commands

- `solaar show` lists devices, including the "Reprogrammable keys" section with divertable controls.
- `solaar config <device>` lists settings with internal names; with a value it sets the setting (and forwards to a running GUI).
- `solaar config <device> divert-keys` shows per-control diversion state.
- `solaar -ddd` logs notifications with feature name, report number, and data.
- `solaar --window=show|hide|only` controls window/tray at launch.
