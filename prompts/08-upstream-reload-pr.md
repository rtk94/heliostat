# Phase 8: Upstream `reload-rules` PR (in the Solaar fork, not this repo)

Do not start this until a GitHub issue on pwr-Solaar/Solaar has agreed the design with the maintainers. Before opening that issue, search existing issues for "reload rules" and "rules.yaml" to avoid a duplicate.

Run Claude Code inside the Solaar fork (`<SOLAAR_FORK_DIR>`, e.g. a clone of `rtk94/Solaar`), then paste:

```
Add a remote "reload-rules" command to Solaar, following the existing "config" remote-command pattern.

- lib/solaar/ui/__init__.py::_command_line: handle args[0] == "reload-rules" by calling diversion.load_config_rule_file() on the GLib main loop, and refresh the rule editor's model if its window is open.
- CLI: <AGREED_COMMAND_SHAPE_FROM_ISSUE>. It registers the Gtk.Application; if remote, forwards ["reload-rules"] (YAML-encoded, as config does); if Solaar is not running, prints that there is nothing to reload.
- Tests in tests/ following the existing style; update docs/rules.md.
- Match the repo's ruff / pre-commit configuration.

Stop and show me the diff, test output, and a manual test transcript (edit ~/.config/solaar/rules.yaml by hand, run the command, show the rule takes effect without restarting Solaar).
```

After the PR is merged and released, back in the Heliostat repo: set the version-gate constant from Phase 2 to that release and make the `auto` reload strategy prefer the remote command.
