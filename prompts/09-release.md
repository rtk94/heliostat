# Phase 9: v1 release

Read CLAUDE.md first. Precondition: Phases 1 to 7 committed and manually verified.

1. README: accurate, no overclaiming. Lead with "Heliostat for Solaar". State the Solaar versions tested (from the conformance suite), what works, what is not supported (Wayland per-app rules outside GNOME, live capture, presets, dry run), and how Heliostat gets Solaar to reload (restart, or the remote command on newer Solaar). Include `pipx install` instructions and screenshots I provide.
2. `.desktop` file with app ID `io.github.rtk94.Heliostat`, a simple original icon (SVG), and installation notes.
3. CHANGELOG.md with a 1.0.0 entry.
4. Update `tools/fetch_solaar.sh` to also pin the newest Solaar release tag, and run `make conformance` against it.
5. Build sdist and wheel; check with `twine check`. Do not upload to PyPI; I do that by hand.

Checkpoint. Stop and show me:
- `make test`, `make lint`, `make conformance` output (including the newest Solaar tag)
- the README for review
- the built artifacts and `twine check` output
