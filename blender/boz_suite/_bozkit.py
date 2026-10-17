"""bozkit for the editor: the SDK checkout's when it is importable, else the copy the editor build
carries (_vendor/bozkit). ``from ._bozkit import world`` imports bozkit.world from either."""
from __future__ import annotations

import importlib

try:
    importlib.import_module("bozkit")
    PACKAGE = "bozkit"
except ModuleNotFoundError:
    PACKAGE = f"{__package__}._vendor.bozkit"


def __getattr__(name: str):
    if name.startswith("__"):
        raise AttributeError(name)
    return importlib.import_module(f"{PACKAGE}.{name}")
