"""Instruction set definitions. Each ISA revision is one module."""

import importlib

DEFAULT = "v0"


def get(name=DEFAULT):
    return importlib.import_module(f"{__name__}.{name}")
