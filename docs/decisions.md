# Decisions and Open Questions

Copied from the claude.ai Project on 2026-10-25. Append decisions as they are made, with date and one line of reasoning. Do not delete superseded decisions; mark them superseded.

## Decisions

- 2026-10-25: Project name is **Heliostat**.
- 2026-10-25: Build on Solaar's rules engine and `rules.yaml` format; do not reimplement HID++.
- 2026-10-25: Delivery vehicle is **standalone app plus a small upstream reload PR**. Standalone gives UX freedom; the reload PR is tiny because Solaar already forwards remote commands to its running instance; Debian 13 ships Solaar 1.1.14, so a restart-based fallback is needed for years regardless.
- 2026-10-25: Rule reload strategy: use the upstream remote command when the installed Solaar supports it (version-gated), otherwise restart Solaar after save. Never rely on the user pressing reload in Solaar's own editor.
- 2026-10-25: License is **GPL-2.0-or-later**. Compatible with Solaar's v2-only and v2-or-later files, permits importing or adapting Solaar code, and matches the license upstream contributions will carry.
- 2026-10-25: **Rules model:** Heliostat owns a typed model of `rules.yaml` and does not import Solaar at runtime. Conformance tests run pinned Solaar 1.1.14 and latest in subprocesses and require Heliostat's output to be byte-identical to Solaar's own save (conformance rule refined 2026-10-26, see "Save target revised"). Decouples Heliostat from Solaar's private APIs across the 1.1.14 to 1.1.20+ span.
- 2026-10-25: **Toolkit:** Qt 6 via PySide6, Qt Widgets (not QML). Native on the KDE dev desktop, mature testing via pytest-qt.
- 2026-10-25: **Device data in v1:** parse `solaar show` / `solaar config` CLI output, with per-version captured fixtures. Live button capture deferred past v1.
- 2026-10-25: **Packaging for v1:** pip-installable pyproject project (pipx/venv). Debian package later; Flatpak deferred (sandbox conflicts with the host `solaar` CLI and `~/.config/solaar`).
- 2026-10-25: **v1 scope:** lossless editing of all rules (simple editor plus advanced tree), diversion awareness with one-click divert, lint/conflict detection, safe save with backups and external-change detection, Apply with reload, `heliostat lint` CLI. Deferred: live capture, dry run, presets, comment preservation.
- 2026-10-25: ~~**Save target:** byte-identical to Solaar's own save, not merely loadable by Solaar.~~ Superseded 2026-10-26 (see below).
- 2026-10-25: **Names:** PyPI distribution `heliostat`, repo `rtk94/heliostat`, app ID `io.github.rtk94.Heliostat`. Name check found no conflicts in the Linux desktop / Logitech space.
- 2026-10-25: **Phase 0** (repo bootstrap) done directly from the planning chat rather than via a Claude Code prompt. Phase prompts live in `prompts/`.
- 2026-10-26: **Save target revised** (supersedes 2026-10-25 "byte-identical to Solaar's own save"). Required: every supported Solaar version loads Heliostat's output as the rules Heliostat holds. Formatting matches Solaar's save byte-for-byte except documented deviations. Deviation D1: Feature arguments are written as loaded; new Feature conditions use underscores, because Solaar 1.1.14 cannot load the spaced form its own save writes (fixed in 1.1.15). Existing misloadable forms are preserved and flagged by lint, never silently rewritten. Found in Phase 1a: on 1.1.14, two saves from Solaar's own editor turn `THUMB_WHEEL` into `None`.
- 2026-10-26: **Broken YAML:** if rules.yaml fails to parse anywhere, Heliostat refuses to edit or save it, reports the error location, and warns that Solaar is running only the rules before the error and will drop the rest on its next save. Found in Phase 1a: Solaar keeps the rules before a YAML error and silently drops the rest.
- 2026-10-26: **Lint additions:** HL000 parse error, HL007 spaced Feature name (error on Solaar < 1.1.15, warning otherwise), HL008 `Feature: None` (feature already lost).
- 2026-10-26: **First upstream contribution** is a one-line docs fix: the published rules example (docs/rules.md) is missing a `---` before `- Feature: CROWN`, so PyYAML stops after 3 of 6 rules. Do this before opening the reload-rules issue. No Debian bug report for the 1.1.14 Feature bug for now.

## Open questions

### Live device data beyond v1
Long-lived concurrent listening for live button capture is unverified. Solaar's own `solaar config` CLI already does short concurrent HID++ access while the GUI runs.

### Upstream reload PR
Search existing pwr-Solaar/Solaar issues before opening one (not possible during planning). Agree the command shape with the maintainers before coding.

### Restart fallback
How Solaar is launched on the dev machine (KDE autostart `.desktop` vs systemd user unit) is unverified. Proven or redesigned at the Phase 2 checkpoint.

### Name collisions (resolved, notes kept)
- PyPI: `heliostat` unregistered. Flathub, Debian, AUR: no results.
- GitHub: many unrelated `heliostat` repos (mostly solar hardware); KubedAI/heliostat is a Ray/Kubernetes console. Use "Heliostat for Solaar" in descriptions for searchability.
- Trademarks not checked. Do not register a placeholder on PyPI; publish at first real release.
