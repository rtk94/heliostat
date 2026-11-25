The example rules file in `docs/rules.md` (the "file with six rules") is missing a `---` before the `- Feature: CROWN` rule. Each rule in `rules.yaml` is its own YAML document, so PyYAML stops at that line with `expected '<document start>', but found '<block sequence start>'`. If you copy the example as-is into `~/.config/solaar/rules.yaml`, only the first three of the six rules load: Solaar logs the error and keeps those three.

This adds the missing separator. It is a one-line, docs-only change.

## Reproduction

Copy the example into a file and count the documents PyYAML can read:

```python
import yaml

n = 0
try:
    for _ in yaml.safe_load_all(open("rules.yaml")):
        n += 1
finally:
    print(n, "rules loaded")
```

| | PyYAML | Solaar's own loader |
|---|---|---|
| Before | 3 rules loaded, then a YAML error at line 18, column 1 (`- Feature: CROWN`) | logs `failed to load from <path>` with the same error, keeps 3 rules |
| After | 6 rules loaded, no error | 6 rules loaded, no error logged |

The example text in `docs/rules.md` is identical at tag 1.1.14, tag 1.1.20 and current master (e7304c4). The PyYAML results are for that text and for this PR's branch. For Solaar's own loader I ran `_load_rule_config` from the real 1.1.14 and 1.1.20 source in a fresh config directory with no display, on the example text before and after this change, and both versions give the results above.

## Why only three rules load

`_load_rule_config` in `lib/logitech_receiver/diversion.py` wraps the whole `yaml.safe_load_all` loop in a try/except. On a YAML error it logs `failed to load from <path>` and keeps the rules parsed before the error. The function is identical in 1.1.14, 1.1.20 and master.

This PR changes only the docs example. It does not touch the loader.
