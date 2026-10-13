"""Instruction set definitions. Each ISA revision is one module."""

import importlib

NAMES = ("v0", "v1a", "v1b")    # the ISAs (v1common is code 1a and 1b share)
DEFAULT = "v0"


def get(name=DEFAULT):
    return importlib.import_module(f"{__name__}.{name}")
