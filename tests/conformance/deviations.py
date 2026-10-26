# SPDX-License-Identifier: GPL-2.0-or-later
"""The documented ways Heliostat's output may differ from Solaar's own save, and nothing else.

Every entry here is a decision recorded in docs/decisions.md. Do not add one without recording the
decision there first.

- D1, Feature names: a Feature argument is written as loaded; Solaar writes str(SupportedFeature).
  Tolerated line by line in the byte comparisons (d1_feature_names).
- D2, argument shapes: every argument is written in the shape it was loaded, one-item lists included;
  Solaar's save rewrites it to the shape its data() returns (then collapses one-item scalar lists), or
  to a fallback. The byte comparisons only use Solaar-canonical input (Solaar's own re-save, rules
  Heliostat builds), where D2 changes nothing, so it is not a line tolerance. On as-written input,
  d2_shape_differences checks what D2 promises.
"""

import difflib
import re
from collections.abc import Callable

_FEATURE_LINE = re.compile(r"^(?P<lead>[ -]*)Feature: (?P<arg>.*)$")


def d1_feature_names(heliostat_line: str, solaar_line: str, tag: str) -> bool:
    """D1: spaces and underscores in a Feature argument compare equal.

    On 1.1.14, Solaar also cannot load the spaced form and saves it as None (the bug D1 exists for),
    so None matches a spaced argument; the semantic tests show both load as None there.
    """
    h, s = _FEATURE_LINE.match(heliostat_line), _FEATURE_LINE.match(solaar_line)
    if not (h and s and h["lead"] == s["lead"]):
        return False
    if h["arg"].replace(" ", "_") == s["arg"].replace(" ", "_"):
        return True
    return tag == "1.1.14" and s["arg"] == "None" and " " in h["arg"]


# Line tolerances for the byte comparisons against Solaar's save. D2 has none (see above).
DEVIATIONS: tuple[Callable[[str, str, str], bool], ...] = (d1_feature_names,)


def formatting_differences(heliostat: str, solaar: str, tag: str) -> str | None:
    """None if the two texts are equal up to DEVIATIONS, else a unified diff for the failure message."""
    h_lines, s_lines = heliostat.splitlines(keepends=True), solaar.splitlines(keepends=True)
    if len(h_lines) == len(s_lines) and all(
        h == s or any(dev(h.rstrip("\n"), s.rstrip("\n"), tag) for dev in DEVIATIONS)
        for h, s in zip(h_lines, s_lines, strict=True)
    ):
        return None
    return "".join(difflib.unified_diff(s_lines, h_lines, f"solaar-{tag}", "heliostat"))


def d2_shape_differences(dumped, loaded, path="$") -> str | None:
    """D2: dumps output, loaded back, has exactly the structure and scalar types the original loaded
    with; no shape is rewritten and no one-item list is collapsed. Returns where they first differ."""
    if type(dumped) is not type(loaded):
        return f"{path}: {dumped!r} != {loaded!r}"
    if isinstance(loaded, dict):
        if set(dumped) != set(loaded):  # PyYAML sorts mapping keys on dump, as in Solaar's save
            return f"{path}: keys {sorted(map(repr, dumped))} != {sorted(map(repr, loaded))}"
        return next((d for k in loaded if (d := d2_shape_differences(dumped[k], loaded[k], f"{path}.{k}"))), None)
    if isinstance(loaded, list):
        if len(dumped) != len(loaded):
            return f"{path}: {dumped!r} != {loaded!r}"
        pairs = enumerate(zip(dumped, loaded, strict=True))
        return next((d for i, (a, b) in pairs if (d := d2_shape_differences(a, b, f"{path}[{i}]"))), None)
    return None if dumped == loaded else f"{path}: {dumped!r} != {loaded!r}"
