# Heliostat for Solaar

A friendlier rules and diversions editor for Logitech devices on Linux. Heliostat edits Solaar's own `~/.config/solaar/rules.yaml` and relies on Solaar for everything device-related. You can stop using Heliostat at any time and lose nothing.

**Status:** pre-alpha. Nothing works yet. See `docs/` for the design and `prompts/` for the build phases.

## Development

```
make venv        # create .venv with Python 3.13 and install dev deps
make test        # unit tests
make lint        # ruff check + format check
make conformance # tests against pinned Solaar versions (from Phase 1a)
```

## License

GPL-2.0-or-later. See `LICENSE`.
