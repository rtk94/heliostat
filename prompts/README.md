# Build prompts

One file per phase. Run them in order. Each one ends at a checkpoint: Claude Code stops and shows output, you check it (paste it into the claude.ai Project chat if you want a second look), commit, and only then start the next file.

## How to run a phase

```
cd /home/rich/Programming/heliostat
git status                       # should be clean before starting a phase
claude                           # start Claude Code in the repo root
```

Then type, for example:

```
Read prompts/01a-conformance-harness.md and do it.
```

Claude Code picks up `CLAUDE.md` automatically. When it stops at the checkpoint, review the output and the diff (`git diff`, `git status`), then commit (or ask Claude Code to commit). Start a fresh session (`/clear` or a new `claude`) for each phase so context stays small.

## Phases

| File | Phase | Before you start | Checkpoint (what you verify) |
|---|---|---|---|
| (done) | 0. Repo bootstrap | | Done from the planning chat |
| `01a-conformance-harness.md` | 1a. Conformance harness | nothing | fetch output, dependency notes, conformance tests green |
| `01b-rules-model.md` | 1b. Rules model | 1a committed | `make test` and `make conformance` green; 1.1.14 vs 1.1.20 differences listed |
| `02-solaar-adapter.md` | 2. Solaar adapter | **capture fixtures by hand (below)** | parser tests green; `heliostat debug-reload` run by hand |
| `03-analysis-lint.md` | 3. Lint | 2 committed | `heliostat lint` against your real rules file |
| `04-simple-rules.md` | 4. Simple-rule mapping | 3 committed | property tests green; recognition stats |
| `05-qt-shell.md` | 5. Read-only GUI | 4 committed | screenshot of `heliostat` on your desktop |
| `06-editing.md` | 6. Editing, save, apply | 5 committed | edit a real rule, Apply, button works, backup written |
| `07-diversion-fixups.md` | 7. One-click divert | 6 committed | un-divert in Solaar, fix from Heliostat |
| `08-upstream-reload-pr.md` | 8. Upstream PR (Solaar fork) | issue agreed with maintainers | diff, tests, manual transcript |
| `09-release.md` | 9. v1 release | 1 to 7 done | README review, conformance on newest Solaar |

## Before Phase 2: capture real Solaar output

Run on this machine with your Logitech devices connected, from the repo root:

```
V=$(solaar --version | awk '{print $2}')
mkdir -p tests/fixtures/solaar/$V
solaar --version > tests/fixtures/solaar/$V/version.txt
solaar show > tests/fixtures/solaar/$V/show_all.txt
solaar config '<DEVICE_NAME_OR_SERIAL>' > tests/fixtures/solaar/$V/config_<SHORT_DEVICE_NAME>.txt
solaar config '<DEVICE_NAME_OR_SERIAL>' divert-keys > tests/fixtures/solaar/$V/divert_keys_<SHORT_DEVICE_NAME>.txt
```

Repeat the last two lines for each device. Replace `<DEVICE_NAME_OR_SERIAL>` with a name from `solaar show` (quoted) and `<SHORT_DEVICE_NAME>` with something filename-safe like `mx-master-3`. Skim the files for anything you don't want in a public repo (serial numbers are probably fine; your call) before committing.

## Before Phase 1b: optional real rules file

If `~/.config/solaar/rules.yaml` exists, copy it to `tests/fixtures/rules/real-rich.yaml` after reviewing it for anything private (Execute actions with paths, hostnames).
