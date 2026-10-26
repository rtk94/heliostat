# Captured Solaar 1.1.20 output

Captured 2026-10-26 on the same machine and devices as `../1.1.14/` (two Bolt receivers, MX Mechanical, Signature M650), using the pinned checkout `.solaar/1.1.20` run by the system interpreter:

```
LANGUAGE=C LC_ALL=C.UTF-8 XDG_CONFIG_HOME=<temp dir> PYTHONPATH=.solaar/1.1.20/lib /usr/bin/python3 .solaar/1.1.20/bin/solaar <args>
```

`XDG_CONFIG_HOME` pointed at a temp directory holding a copy of the real `~/.config/solaar/config.yaml`, so 1.1.20 never touched the real config used by the installed 1.1.14. All commands were read-only (no setting values). Devices were addressed by serial.

| File | Command |
|---|---|
| `version.txt` | `solaar --version` |
| `show_all.txt` | `solaar show` |
| `config_mx-mechanical.txt` | `solaar config <keyboard serial>` |
| `config_signature-m650.txt` | `solaar config <mouse serial>` |
| `divert_keys_*.txt` | `solaar config <serial> divert-keys` (all controls `Regular`) |

## Observation

Even with only read-only commands, 1.1.20 rewrote the copied `config.yaml`: the version stamp changed from `1.1.14-4` to `1.1.20` and the `_absent` setting lists were restructured. A newer Solaar silently upgrades the config file the first time it runs against it.

## Redaction

Same mapping as `../1.1.14/README.md`: receiver serials -> `000...0001` / `000...0002`; device serial / unit ID: MX Mechanical -> `AAAA0001`, Signature M650 -> `AAAA0002`; Easy-Switch host names -> `host-a`, `host-b`. Product identifiers unchanged.
