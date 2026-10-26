# SPDX-License-Identifier: GPL-2.0-or-later
"""Type-strict equality for JSON-like data, so 1, 1.0 and True do not compare equal."""


def assert_same_data(actual, expected, path="$"):
    assert type(actual) is type(expected), f"{path}: {actual!r} ({type(actual).__name__}) != {expected!r}"
    if isinstance(expected, dict):
        assert list(actual) == list(expected), f"{path}: keys {list(actual)} != {list(expected)}"
        for key in expected:
            assert_same_data(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert len(actual) == len(expected), f"{path}: length {len(actual)} != {len(expected)}: {actual!r}"
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            assert_same_data(a, e, f"{path}[{i}]")
    else:
        assert actual == expected, f"{path}: {actual!r} != {expected!r}"
