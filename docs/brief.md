# Heliostat: Project Brief

## One-liner

A friendlier rules and diversions editor for Logitech devices on Linux, built on top of Solaar's existing HID++ stack and `rules.yaml` format.

## Name

A heliostat is a mirror that tracks the sun and redirects its light; the tool redirects ("diverts") Solaar's device events.

## Problem

Solaar's protocol layer (receiver pairing, feature enumeration, divert/undivert, device quirks) works well. Its rule editor is the pain point: rules are a nested condition/action tree edited through a GTK3 TreeView, and users have to know Logitech control names, the evaluation semantics, and that a control must be diverted before any rule fires on it.

## Principles

- Do not reimplement HID++. Solaar owns the device layer.
- Round-trip compatibility: Heliostat reads and writes Solaar's own `rules.yaml`, byte-identical to Solaar's own save. A user can drop Heliostat at any time and lose nothing.
- Plain language first, raw tree second. Advanced users can still reach the full rule structure.
- Single-maintainer scope. Every v1 feature must be something one person can build and keep working.

## Non-goals

- Per-app (Process / MouseProcess) rules on Wayland beyond what Solaar already supports.
- Device settings, pairing, battery UI. Solaar already does these.
- A new rules language or file format.

See `CLAUDE.md` for v1 scope and design rules, and `docs/decisions.md` for the decision record.
