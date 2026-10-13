"""The ISA registry.

Object files and command lines name an ISA ("v1b"). The study that defines
an ISA registers the module implementing it when the study is imported, so
infra never has to know which studies exist:

    from heron.infra import isas
    isas.register("v1b", "heron.studies.v1_isa.v1b")
"""

import importlib

_MODULES = {}


def register(name, module):
    """Register the module (an import path) that implements ISA `name`."""
    _MODULES[name] = module


def names():
    return tuple(_MODULES)


def get(name):
    if name not in _MODULES:
        known = ", ".join(_MODULES) or "none: import the study that defines it"
        raise KeyError(f"unknown ISA {name!r} (known: {known})")
    return importlib.import_module(_MODULES[name])
