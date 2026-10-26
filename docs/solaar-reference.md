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

## Reload behavior

- `diversion.load_config_rule_file()` runs once at module import, and again only when the user hits reload inside Solaar's own rule editor.
- No file watcher. The only IPC is the remote command channel above, which has no reload command.
- Consequence: an external process that writes `rules.yaml` will NOT change live behavior until Solaar restarts or the user reloads from Solaar's editor.

## Evaluation semantics (summary of the docs)

- A rule is a sequence of components: sub-rules, conditions, actions.
- Components evaluate in order. A false condition stops the rule. If the last thing a rule does is execute an action, no further rules are processed for that notification.
- `Or` short-circuits on true; `And` evaluates like a rule; `Not` negates.
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
