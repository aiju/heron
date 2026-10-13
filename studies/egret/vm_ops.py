"""The bytecode's opcode names, read from vm/compiler.h (so they can't
drift from the VM)."""

import os
import re

_h = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vm", "compiler.h")
with open(_h) as _f:
    _text = _f.read()
_enum = _text[_text.index("enum {\n    OP_HALT"):]
_enum = _enum[:_enum.index("NOPCODES")]
_enum = re.sub(r"/\*.*?\*/", "", _enum, flags=re.S)
OPCODES = [n[3:] for n in re.findall(r"\bOP_\w+", _enum)]
