"""The compiler's intermediate representation and target-independent passes.

The IR is independent of the source language and of the instruction set:
frontends (cc, for C) build it, ir.passes improves it, and a backend in
codegen turns it into assembly for one ISA. See compiler.md.
"""
