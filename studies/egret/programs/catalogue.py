"""The programs: their source, input and expected output.

A program ported from the draft 1 suite (studies/v1_isa/programs) prints
exactly what the suite's expected output says, so its cycles compare with
the hand-written assembly and the compiled C. Egret's own programs have
their expected output in expected/, written by `heron egret test --update`
from the host build and checked by hand.

A line `#! input: FILE` near the top names the program's console input
(relative to the program's folder).
"""

import os
import re

from heron import ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
SUITE_EXPECTED = os.path.join(ROOT, "studies", "v1_isa", "programs", "expected")


class Program:
    def __init__(self, name):
        self.name = name
        self.path = os.path.join(HERE, name + ".eg")
        with open(self.path, "rb") as f:
            self.source = f.read()
        self.input = input_for(self.path)
        suite = os.path.join(SUITE_EXPECTED, name + ".txt")
        self.own_expected = not os.path.exists(suite)
        self.expected_path = os.path.join(HERE, "expected", name + ".txt") if self.own_expected else suite

    def expected(self):
        if not os.path.exists(self.expected_path):
            return None
        with open(self.expected_path, "rb") as f:
            return f.read()


def input_for(path, override=None):
    if override:
        with open(override, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        head = f.read(2000).decode("latin-1")
    m = re.search(r"^#! input: (\S+)", head, re.M)
    if not m:
        return b""
    with open(os.path.join(os.path.dirname(path), m.group(1)), "rb") as f:
        return f.read()


def names():
    return sorted(f[:-3] for f in os.listdir(HERE) if f.endswith(".eg"))


def program(name):
    return Program(name)
