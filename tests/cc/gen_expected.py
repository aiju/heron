"""Write tests/cc/expected/NAME.txt for each tests/cc/NAME.c by compiling it
with the host's C compiler (gcc -funsigned-char, since plain char is
unsigned on this machine) and running it. The tests avoid anything that
depends on the size of long or of pointers.

    python3 tests/cc/gen_expected.py [NAME...]
"""

import glob
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def main(names):
    paths = sorted(glob.glob(os.path.join(HERE, "*.c")))
    if names:
        paths = [p for p in paths if os.path.basename(p)[:-2] in names]
    with tempfile.TemporaryDirectory() as tmp:
        for p in paths:
            name = os.path.basename(p)[:-2]
            with open(p) as f:
                if "/* expected output is hand-written */" in f.read():
                    continue
            exe = os.path.join(tmp, name)
            subprocess.run(["gcc", "-funsigned-char", "-fwrapv", "-w", "-O1", "-o", exe, p], check=True)
            out = subprocess.run([exe], capture_output=True, check=True).stdout
            with open(os.path.join(HERE, "expected", name + ".txt"), "wb") as f:
                f.write(out)
            print(f"{name}: {len(out)} bytes")


if __name__ == "__main__":
    main(sys.argv[1:])
