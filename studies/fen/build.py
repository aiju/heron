"""Building Fen: the kernel, the C library, the programs, the boot image
and the disk.

- **The kernel** (kernel/) is C and assembly, compiled with all its data
  far (32-bit addresses, since it runs in the window at 0x8000_0000, which
  16-bit absolute addresses can't reach) and linked at 0x8000_0000 with
  its vectors first. syscalls.py's table gives its SWI vectors and stubs.
- **The C library** (lib/) is an archive the programs are linked with,
  with the compiler's string and ctype functions.
- **A program** is linked at USER_BASE (0x1000) with lib/crt0.s first and
  converted to Fen's executable format (fen/abi.h): a header and the
  image, its text on pages of its own.
- **The boot image** is the kernel, then from the next page the boot
  archive: the programs the system needs before it has a file system.
- **The disk** is a file system image (mkfs.py) with every program in /bin.

Everything goes to build/fen/. Compiling is cached by the source's text
and its headers', so a rebuild only compiles what changed.
"""

import hashlib
import os
import pickle
import struct

from heron import BUILD, ROOT
from heron.infra import asm as asmcore
from heron.infra import isas
from heron.infra import link as L
from heron.infra import obj as O
from heron.studies.c_compiler.cc import driver
from heron.studies.c_compiler.cc.lex import CompileError
import heron.studies.v2_isa  # noqa: F401  (registers the ISA)

from . import syscalls

ISA = "v2"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BUILD, "fen")
GEN = os.path.join(OUT, "gen")
CACHE = os.path.join(OUT, "cache")
CC_INCLUDE = os.path.join(ROOT, "studies", "c_compiler", "cc", "include")
CC_LIB = os.path.join(ROOT, "studies", "c_compiler", "cc", "lib")
INCLUDE = [os.path.join(HERE, "include"), GEN, CC_INCLUDE]

KERNEL_BASE = 0x80000000
USER_BASE = 0x1000
USER_TOP = 0x00800000           # programs and their heaps end below the mmap area
FX_MAGIC = 0x584E4546
BOOT_MAGIC = 0x424E4546
PAGE = 4096

KERNEL_SOURCES = ["entry.s", "fastipc.s", "main.c", "klib.c", "mem.c", "proc.c", "ipc.c", "trap.c", "sys.c",
                  "iop.c"]

LIB_SOURCES = ["ipc.s", "start.c", "fd.c", "stdio.c", "stdlib.c", "string2.c", "spawn.c",
               "time.c", "getopt.c", "srv.c", "gui.c"]
CC_LIB_SOURCES = ["string.c", "ctype.c"]

# the graphics study's library, which the window system draws with
GRAPHICS_SRC = os.path.join(ROOT, "studies", "graphics", "src")
GRAPHICS_LIB = ["theme.c", "gfx.c", "line.c", "ellipse.c", "raster.c", "blit.c", "expand.c",
                "font.c", "ttf.c"]
FONTS = os.path.join(GEN, "fonts.s")

# programs: name -> sources, relative to the study (or absolute). Every
# cmd/NAME.c is one too (programs()).
SERVERS = {
    "fs": ["srv/fs/main.c", "srv/fs/fenfs.c", "srv/fs/cache.c", "srv/fs/ide.c", "srv/fs/ideio.s"],
    # the file server with the disk behind the I/O processor (studies/iop)
    "fs-iop": ["srv/fs/main.c", "srv/fs/fenfs.c", "srv/fs/cache.c", "srv/fs/ide_iop.c"],
    "cons": ["srv/cons/main.c"],
    "wsys": ["srv/wsys/main.c", "srv/wsys/gwm.c", "srv/wsys/input.c", "srv/wsys/kernels.s", FONTS]
            + [os.path.join(GRAPHICS_SRC, f) for f in GRAPHICS_LIB],
}
# the include directories a program needs besides INCLUDE
PROGRAM_INCLUDE = {"wsys": [os.path.join(HERE, "srv", "wsys"), GRAPHICS_SRC]}
# and the defines: wsys has the fill and blit kernels in draft 2's
# assembly (srv/wsys/kernels.s); fs-iop's cache is in pages of its own
PROGRAM_DEFINES = {"wsys": {"GFX_ASM": "1"}, "fs-iop": {"IOP_DISK": "1"}}

# what the boot archive holds: init, and the servers it starts before
# there's a file system
BOOT = ["init", "fs", "cons"]

# programs that are only for the boot archive or the tests, not /bin
NOT_IN_BIN = {"init", "ktest", "ktchild", "ktcrash", "ktspin", "fs-iop"}


def programs():
    """{name: [sources]} for every program."""
    out = {n: list(s) for n, s in SERVERS.items()}
    for f in sorted(os.listdir(os.path.join(HERE, "cmd"))):
        if f.endswith(".c"):
            out[f[:-2]] = [os.path.join("cmd", f)]
    return out


class BuildError(Exception):
    pass


def ensure_dirs():
    for d in (OUT, GEN, CACHE, os.path.join(GEN, "fen")):
        os.makedirs(d, exist_ok=True)


def write_if_changed(path, text):
    try:
        with open(path) as f:
            if f.read() == text:
                return
    except OSError:
        pass
    with open(path, "w") as f:
        f.write(text)


def generate():
    """The files syscalls.py makes."""
    ensure_dirs()
    write_if_changed(os.path.join(GEN, "ksys.s"), syscalls.kernel_stubs())
    write_if_changed(os.path.join(GEN, "usys.s"), syscalls.user_stubs())
    write_if_changed(os.path.join(GEN, "fen", "sysno.h"), syscalls.header())
    write_if_changed(FONTS, fonts_asm())


def fonts_asm():
    """The window system's two bitmap fonts, as the graphics study makes
    them."""
    from heron.studies.graphics import fonts
    out = ["; the graphics study's bitmap fonts (studies/graphics/fonts.py)", ""]
    for name, data in fonts.blobs().items():
        if not name.startswith("font_"):
            continue
        sym = "_" + name
        out += [f"        .global {sym}", f"        .far {sym}", f"        .section .fardata.{sym}",
                "        .align 4", f"{sym}:"]
        for k in range(0, len(data), 16):
            out.append("        .byte " + ", ".join(str(b) for b in data[k:k + 16]))
        out.append("")
    return "\n".join(out)


def _headers(path, include, seen=None):
    """The text of a file's headers, recursively, for the cache key."""
    import re
    seen = set() if seen is None else seen
    out = []
    try:
        with open(path) as f:
            text = f.read()
    except OSError:
        return out
    for m in re.finditer(r'#\s*include\s*[<"]([^>"]+)[>"]', text):
        name = m.group(1)
        for d in [os.path.dirname(path)] + list(include):
            p = os.path.join(d, name)
            if os.path.exists(p):
                if p not in seen:
                    seen.add(p)
                    with open(p) as f:
                        out.append(f.read())
                    out += _headers(p, include, seen)
                break
    return out


def _cached(key, name, make):
    h = hashlib.sha256(pickle.dumps(key)).hexdigest()[:24]
    path = os.path.join(CACHE, h + ".o")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return O.ObjectFile.from_bytes(f.read(), name)
    o = make()
    o.write(path)
    return o


def compile_c(path, include=INCLUDE, window=False, defines=None):
    """A C file as an object file; `window` for the kernel's."""
    with open(path) as f:
        text = f.read()
    key = ("c", path, text, _headers(path, include), tuple(include), window,
           sorted((defines or {}).items()), _compiler_version())

    def make():
        try:
            u = driver.compile_unit(path, ISA, include, defines)
            asm = driver.unit_assembly(u, ISA, window=window)
        except CompileError as e:
            raise BuildError(f"{os.path.relpath(path, ROOT)}: {e}") from None
        return driver.assemble(ISA, asm, os.path.basename(path)[:-2] + ".o")
    return _cached(key, os.path.basename(path)[:-2] + ".o", make)


def assemble_file(path, prefix=""):
    """An assembly file as an object file; `prefix` is text put in front of
    it (the kernel's offsets, for fastipc.s)."""
    with open(path) as f:
        text = prefix + f.read()
    key = ("s", path, text, _compiler_version())

    def make():
        a = asmcore.Assembler(isas.get(ISA), relocatable=True)
        try:
            a.load(path, text=text)
            return a.assemble_object(os.path.basename(path)[:-2] + ".o")
        except asmcore.AsmError as e:
            raise BuildError(str(e)) from None
    return _cached(key, os.path.basename(path)[:-2] + ".o", make)


_version = None


def _compiler_version():
    """A stamp of the compiler's and assembler's sources, so the cache
    forgets what an older compiler made."""
    global _version
    if _version is None:
        h = hashlib.sha256()
        roots = [os.path.join(ROOT, "studies", "c_compiler"), os.path.join(ROOT, "studies", "v2_isa", "isa", "src"),
                 os.path.join(ROOT, "infra", "toolchain", "src")]
        for r in roots:
            for d, _, files in sorted(os.walk(r)):
                for f in sorted(files):
                    if f.endswith((".py", ".rs")):
                        with open(os.path.join(d, f), "rb") as fh:
                            h.update(fh.read())
        _version = h.hexdigest()[:16]
    return _version


def obj_for(path, include=INCLUDE, window=False, defines=None):
    if path.endswith(".s"):
        return assemble_file(path)
    return compile_c(path, include, window, defines)


def image_bytes(img, lo, hi):
    out = bytearray(hi - lo)
    for a, b in img.mem.items():
        if lo <= a < hi:
            out[a - lo] = b
    return bytes(out)


# ---- the kernel ------------------------------------------------------------

def kernel_offsets(defines=None):
    """kernel/offsets.c's constants as .equ lines: compiled, and read back
    from what the compiler makes of them (a label and its four bytes)."""
    import re
    include = [os.path.join(HERE, "kernel")] + INCLUDE
    path = os.path.join(HERE, "kernel", "offsets.c")
    with open(path) as f:
        text = f.read()
    key = ("offsets", text, _headers(path, include), sorted((defines or {}).items()),
           _compiler_version())
    cache = os.path.join(CACHE, hashlib.sha256(pickle.dumps(key)).hexdigest()[:24] + ".equ")
    if os.path.exists(cache):
        with open(cache) as f:
            return f.read()
    try:
        u = driver.compile_unit(path, ISA, include, defines)
        asm = driver.unit_assembly(u, ISA, window=True)
    except CompileError as e:
        raise BuildError(f"kernel/offsets.c: {e}") from None
    vals = {}
    for m in re.finditer(r"^_(\w+):\n\s+\.byte ([\d, ]+)$", asm, re.M):
        vals[m.group(1)] = int.from_bytes(bytes(int(b) for b in m.group(2).split(",")), "little")
    for m in re.finditer(r"^_(\w+):\n\s+\.(space|fill) 4\b", asm, re.M):
        vals[m.group(1)] = 0
    names = re.findall(r"^(?:OFF|K)\((\w+),", text, re.M)
    missing = [n for n in names if n not in vals]
    if missing:
        raise BuildError(f"kernel/offsets.c: no value for {', '.join(missing)}")
    # fastipc.s indexes the tables with LEAs that multiply by these
    if vals["PT_SIZE"] != 20 or vals["T_SIZE"] != 72:
        raise BuildError(f"kernel/fastipc.s indexes ports by 20 bytes and threads by 72; "
                         f"they are {vals['PT_SIZE']} and {vals['T_SIZE']}")
    out = "; kernel/offsets.c, as the build read it\n" + "".join(
        f"        .equ {n}, {vals[n]}\n" for n in names) + "\n"
    with open(cache, "w") as f:
        f.write(out)
    return out


def fastipc(offsets, defines=None):
    """kernel/fastipc.s with the offsets in front; with COPY_UR, each BCOPY
    done instead with MFUR and MTUR, through the registers its comment
    names."""
    import re
    path = os.path.join(HERE, "kernel", "fastipc.s")
    if not (defines or {}).get("COPY_UR"):
        return assemble_file(path, offsets)

    def expand(m):
        rd, rs, regs = m.group(1), m.group(2), m.group(3).split()
        out = [f"        MTSR bank, {rs}"]
        out += [f"        MFUR {r}, r{i}" for i, r in enumerate(regs)]
        out += [f"        MTSR bank, {rd}"]
        out += [f"        MTUR r{i}, {r}" for i, r in enumerate(regs)]
        return "\n".join(out)
    with open(path) as f:
        text = re.sub(r"^\s+BCOPY (r\d+), (r\d+)\s+; COPY_UR: ((?:r\d+ ?){8})$", expand,
                      f.read(), flags=re.M)
    if "BCOPY" in re.sub(r";.*", "", text):
        raise BuildError("kernel/fastipc.s: a BCOPY without the registers for COPY_UR")
    out = os.path.join(GEN, "fastipc_ur.s")
    write_if_changed(out, text)
    return assemble_file(out, offsets)


def kernel(defines=None):
    """The kernel's image (bytes from physical 0) and its linked image."""
    generate()
    include = [os.path.join(HERE, "kernel")] + INCLUDE
    offsets = kernel_offsets(defines)
    write_if_changed(os.path.join(GEN, "koffsets.s"), offsets)
    objs = [fastipc(offsets, defines) if s == "fastipc.s"
            else obj_for(os.path.join(HERE, "kernel", s), include, window=True, defines=defines)
            for s in KERNEL_SOURCES]
    objs.append(assemble_file(os.path.join(GEN, "ksys.s")))
    try:
        img = L.link(objs, [], ISA, mem_top=KERNEL_BASE + 0x01000000)
    except L.LinkError as e:
        raise BuildError(f"linking the kernel: {e}") from None
    end = img.symbols["__end"]
    return image_bytes(img, KERNEL_BASE, end), img


# ---- the C library and programs ---------------------------------------------

_libc = None


def libc():
    """The C library: [(member name, ObjectFile)]."""
    global _libc
    if _libc is None:
        generate()
        members = []
        for s in LIB_SOURCES:
            members.append((s[:-2] + ".o", obj_for(os.path.join(HERE, "lib", s))))
        for s in CC_LIB_SOURCES:
            members.append((s[:-2] + ".o", obj_for(os.path.join(CC_LIB, s))))
        members.append(("usys.o", assemble_file(os.path.join(GEN, "usys.s"))))
        _libc = members
    return _libc


def link_program(sources, include=INCLUDE, extra_libs=(), defines=None):
    """Link a program's sources (paths) with crt0 and the C library."""
    objs = [assemble_file(os.path.join(HERE, "lib", "crt0.s"))]
    objs += [obj_for(p, include, defines=defines) for p in sources]
    try:
        return L.link(objs, [libc()] + list(extra_libs), ISA, base=USER_BASE, entry="__start",
                      mem_top=USER_TOP)
    except L.LinkError as e:
        raise BuildError(f"linking {os.path.basename(sources[0])}: {e}") from None


def executable(img, stack=0):
    """A linked program in Fen's executable format (fen/abi.h)."""
    s = img.symbols
    base, end = USER_BASE, s["__end"]
    data = image_bytes(img, base, end)
    # trailing zeros (the bss) needn't be in the file
    n = len(data.rstrip(b"\0"))
    n = (n + 3) & ~3
    hdr = struct.pack("<8I", FX_MAGIC, s["__start"], base, n, end - base,
                      s["__text_start"], s["__text_end"], stack)
    return hdr + data[:n]


def program(name, sources=None, include=None):
    """Build one program: its executable, written to build/fen/bin/NAME."""
    generate()
    sources = sources or [os.path.join(HERE, p) for p in programs()[name]]
    include = include or PROGRAM_INCLUDE.get(name, []) + INCLUDE
    img = link_program(sources, include, defines=PROGRAM_DEFINES.get(name))
    fx = executable(img)
    os.makedirs(os.path.join(OUT, "bin"), exist_ok=True)
    with open(os.path.join(OUT, "bin", name), "wb") as f:
        f.write(fx)
    return fx, img


def boot_archive(modules):
    """[(name, bytes)] as the archive kernel/main.c reads."""
    hdr_size = 8 + 32 * len(modules)
    off = (hdr_size + 15) & ~15
    entries, blobs = [], []
    for name, data in modules:
        entries.append(struct.pack("<24sII", name.encode(), off, len(data)))
        blobs.append(data + b"\0" * (-len(data) % 16))
        off += len(data) + (-len(data) % 16)
    head = struct.pack("<II", BOOT_MAGIC, len(modules)) + b"".join(entries)
    head += b"\0" * (-len(head) % 16)
    return head + b"".join(blobs)


def boot_image(modules=None, kernel_defines=None):
    """The kernel, and the boot archive from the page after it: bytes to put
    at physical 0. Also the kernel's linked image (for its symbols).
    `modules` are the archive's programs: names, or (name, program) to put
    a program in under another name."""
    kbytes, kimg = kernel(kernel_defines)
    names = modules if modules is not None else BOOT
    mods = []
    for n in names:
        name, prog = n if isinstance(n, tuple) else (n, n)
        mods.append((name, program(prog)[0]))
    pad = -len(kbytes) % PAGE
    return kbytes + b"\0" * pad + boot_archive(mods), kimg


# ---- the disk -----------------------------------------------------------------

DISK_SIZE = 8 << 20

PROFILE = """\
# /etc/profile: what a login shell does first
export PATH=/bin
cat /etc/motd
"""

MOTD = """\
Welcome to Fen. Try ls /bin, ps, cat /etc/hello.txt, or help.
"""

MENU = """\
# /etc/menu: the desktop's menu, "label: command"
Terminal: /bin/term
Clock: /bin/clock
"""

HELLO = """\
Fen is an operating system for Heron, draft 2: a small kernel that passes
messages between threads in their own register banks, a file server, a
console server and a window system in user space, and a shell.
"""


def disk(extra=None, size=DISK_SIZE):
    """The CF card's image: every program in /bin, and a little in /etc."""
    from . import mkfs
    files = {}
    for name in programs():
        if name in NOT_IN_BIN:
            continue
        files[f"/bin/{name}"] = program(name)[0]
    files["/etc/profile"] = PROFILE.encode()
    files["/etc/motd"] = MOTD.encode()
    files["/etc/hello.txt"] = HELLO.encode()
    files["/etc/menu"] = MENU.encode()
    files.update(extra or {})
    return mkfs.make(files, size=size, dirs=["/home", "/tmp", "/dev"], now=1792108800)
