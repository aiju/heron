"""The compiler's intermediate representation and target-independent passes.

The IR is independent of the source language and of the instruction set:
frontends (tmc.cc for C) build it, tmc.ir.passes improves it, and a backend
in tmc.codegen turns it into assembly for one ISA. See docs/compiler.md.
"""
