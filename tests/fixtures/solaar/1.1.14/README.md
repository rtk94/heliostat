# Captured Solaar 1.1.14 output

Captured 2026-10-26 on Debian 13 (`solaar 1.1.14-4`) with two Bolt receivers, an MX Mechanical keyboard and a Signature M650 mouse. All commands were read-only except the Back Button round trip below.

| File | Command |
|---|---|
| `version.txt` | `solaar --version` |
| `show_all.txt` | `solaar show` |
| `config_mx-mechanical.txt` | `solaar config 'MX Mechanical'` |
| `config_signature-m650.txt` | `solaar config 'Signature M650 Mouse'` |
| `divert_keys_*.txt` | `solaar config '<device>' divert-keys` (all controls `Regular`) |
| `divert_keys_signature-m650_back-diverted.txt` | same, after `solaar config 'Signature M650 Mouse' divert-keys 'Back Button' Diverted` |
| `set_mouse_gestures_signature-m650_back.txt` | output of `solaar config 'Signature M650 Mouse' divert-keys 'Back Button' 'Mouse Gestures'` |
| `divert_keys_signature-m650_back-gestures.txt` | `divert-keys` read back after that set |
| `show_all_back-gestures.txt` | `solaar show` with the Back Button set to `Mouse Gestures` (second round trip, 2026-10-26 01:12) |

The Back Button was set back to `Regular` afterwards, and `~/.config/solaar/config.yaml` was verified byte-identical to a backup taken before the round trip.

## Observation (cause confirmed in Phase 2)

After setting the Back Button to `Mouse Gestures`, reading `divert-keys` from a separate `solaar config` process reports it as `Diverted`: the device stores only a divert bit, and Solaar keeps the gesture mode in its own process and `config.yaml`.

`show_all_back-gestures.txt` confirms the saved mode is readable: its "Key/Button Diversion (saved)" line for the M650 reads `Back Button:Mouse Gestures` while the live line reads `Back Button:Diverted`. During that set, `config.yaml` held `divert-keys: {82: 0, 83: 2, 86: 0}`. After restoring `Regular`, `config.yaml` was again byte-identical to the backup.

## Redaction

Identifying values were replaced consistently across all files, keeping the original format:

- Receiver serials -> `00000000000000000000000000000001`, `...0002`
- Device serial / unit ID: MX Mechanical -> `AAAA0001`, Signature M650 -> `AAAA0002`
- Easy-Switch host names -> `host-a`, `host-b`

Product identifiers (WPID, model ID, codenames, firmware versions) are unchanged.
