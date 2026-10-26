# SPDX-License-Identifier: GPL-2.0-or-later
"""Simple rules: recognize the common rule shape, generate it back unchanged, and describe it."""

from heliostat.simple.describe import describe
from heliostat.simple.rule import (
    ACTION_TYPES,
    TRIGGER_KEY_ACTIONS,
    GestureTrigger,
    KeyTrigger,
    NotSimple,
    SimpleAction,
    SimpleRule,
    Trigger,
    generate,
    not_simple_reason,
    recognize,
)

__all__ = [
    "ACTION_TYPES",
    "TRIGGER_KEY_ACTIONS",
    "GestureTrigger",
    "KeyTrigger",
    "NotSimple",
    "SimpleAction",
    "SimpleRule",
    "Trigger",
    "describe",
    "generate",
    "not_simple_reason",
    "recognize",
]
