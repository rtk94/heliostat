# Phase 2: Solaar adapter

Read CLAUDE.md first. Precondition: `tests/fixtures/solaar/<version>/` contains real captured output (`version.txt`, `show_all.txt`, `config_*.txt`, `divert_keys_*.txt`). If it is empty, stop and tell me; I capture these by hand (see prompts/README.md). Never run `solaar config` with a value, and never kill or restart Solaar, during this session.

1. `src/heliostat/solaar/`: a `SolaarClient` Protocol:
   - `version() -> tuple[int, int, int]`
   - `is_running() -> bool`
   - `devices() -> list[Device]` (name, codename, serial, unit_id, kind, online)
   - `controls(device) -> list[Control]` (Logitech name, divertable: bool, current diversion mode)
   - `set_divert(device, control, mode) -> None`
   - `reload_rules() -> ReloadResult`

2. `CliSolaarClient`: runs the `solaar` binary via subprocess with timeouts. Parsers for `show`, `config`, and `divert-keys` output are pure functions over strings, tested against every file under `tests/fixtures/solaar/*/`. Unrecognized output raises `SolaarOutputError` carrying the raw text; never guess. Read `.solaar/<tag>/lib/solaar/cli/show.py` and `config.py` to understand the formats, but the fixtures are the ground truth.

3. `reload_rules()`: strategy setting `auto | remote | restart`, default `restart`. The remote command doesn't exist upstream yet; add a version-gate constant set to `None` and make `auto` fall back to `restart` while it is `None`.
   Restart: find the running Solaar process, record its argv, SIGTERM it, wait (bounded), then relaunch with the same argv, detached (new session, no inherited stdio). If Solaar runs under a systemd user unit, use `systemctl --user restart <unit>` instead. Report exactly what happened in `ReloadResult`.

   Known on the dev machine (2026-10-26): Solaar runs as the systemd user unit `app-solaar@autostart.service` (KDE generates it from `/etc/xdg/autostart/solaar.desktop`), command `/usr/bin/solaar --window=hide`. Detect this generally (find the unit owning the Solaar PID, e.g. via `systemctl --user status <pid>`) rather than hard-coding the unit name, and prefer `systemctl --user restart <unit>` when a unit owns the process.

4. `FakeSolaar` implementing the same Protocol, for tests in later phases.

Note on diversion modes: `tests/fixtures/solaar/1.1.14/README.md` records that after setting a control to `Mouse Gestures`, a separate `solaar config` read reports it as `Diverted`. Confirm the cause in the pinned source. If the CLI cannot distinguish the two, `controls()` must report the mode as "diverted (gesture mode unknown)" rather than guessing, and say so in the checkpoint.

5. A `heliostat debug-reload` subcommand that calls `reload_rules()` on the real system and prints the `ReloadResult`. Do NOT run it yourself; I run it by hand.

Checkpoint. Stop and show me:
- `make test` and `make lint` output
- parser coverage per fixture file (which files parsed, what was extracted)
- the exact restart procedure the code will follow, so I can sanity-check it before running `heliostat debug-reload`
