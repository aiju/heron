"""Fen's file system on the host: making an image (the CF card's
contents) from files, and reading one back, for the build and the tests.
The format is include/fen/fenfs.h's.
"""

import struct
import time

BLOCK = 1024
MAGIC = 0x464E4546
ROOT = 1
NDIRECT = 11
PER_BLOCK = BLOCK // 4
INODES_PER_BLOCK = BLOCK // 64
NAME = 28

S_IFREG = 0x8000
S_IFDIR = 0x4000
S_IFCHR = 0x2000

DEVICES = {"null": 1, "zero": 2, "klog": 3}


class FsError(Exception):
    pass


class Image:
    """A file system being made, in memory."""

    def __init__(self, size=8 << 20, ninodes=1024, now=None):
        self.nblocks = size // BLOCK
        self.ninodes = ninodes
        self.now = int(time.time()) if now is None else now
        self.bitmap_start = 2
        self.bitmap_blocks = (self.nblocks + BLOCK * 8 - 1) // (BLOCK * 8)
        self.inode_start = self.bitmap_start + self.bitmap_blocks
        self.inode_blocks = (ninodes + INODES_PER_BLOCK - 1) // INODES_PER_BLOCK
        self.data_start = self.inode_start + self.inode_blocks
        self.data = bytearray(self.nblocks * BLOCK)
        self.next_block = self.data_start
        self.next_inode = ROOT
        self.inodes = {}        # ino -> [mode, nlink, size, mtime, blocks]
        self.dirs = {}          # ino -> [(name, ino)]
        root = self.new_inode(S_IFDIR | 0o755)
        assert root == ROOT
        self.dirs[root] = [(".", root), ("..", root)]
        self.inodes[root][1] = 2

    def new_inode(self, mode):
        ino = self.next_inode
        if ino >= self.ninodes:
            raise FsError("out of inodes")
        self.next_inode += 1
        self.inodes[ino] = [mode, 1, 0, self.now, []]
        return ino

    def alloc(self):
        b = self.next_block
        if b >= self.nblocks:
            raise FsError("the image is full")
        self.next_block += 1
        return b

    def lookup(self, path, make=True):
        """The directory inode for a path of directories, made as needed."""
        ino = ROOT
        for part in [p for p in path.split("/") if p]:
            for name, child in self.dirs[ino]:
                if name == part:
                    if child not in self.dirs:
                        raise FsError(f"{path}: {part} isn't a directory")
                    ino = child
                    break
            else:
                if not make:
                    raise FsError(f"{path}: no such directory")
                d = self.new_inode(S_IFDIR | 0o755)
                self.inodes[d][1] = 2
                self.dirs[d] = [(".", d), ("..", ino)]
                self.dirs[ino].append((part, d))
                self.inodes[ino][1] += 1
                ino = d
        return ino

    def mkdir(self, path):
        self.lookup(path)

    def _link(self, path, ino):
        parent, _, name = path.rstrip("/").rpartition("/")
        if len(name.encode()) >= NAME:
            raise FsError(f"{path}: the name is too long")
        d = self.lookup(parent)
        if any(n == name for n, _ in self.dirs[d]):
            raise FsError(f"{path} exists")
        self.dirs[d].append((name, ino))

    def add_file(self, path, data, mode=0o644):
        ino = self.new_inode(S_IFREG | mode)
        self.inodes[ino][2] = len(data)
        blocks = []
        for off in range(0, len(data), BLOCK):
            b = self.alloc()
            chunk = data[off:off + BLOCK]
            self.data[b * BLOCK:b * BLOCK + len(chunk)] = chunk
            blocks.append(b)
        self.inodes[ino][4] = blocks
        self._link(path, ino)
        return ino

    def add_device(self, path, kind):
        ino = self.new_inode(S_IFCHR | 0o666)
        self.inodes[ino][4] = [DEVICES[kind]]
        self._link(path, ino)

    def _block_map(self, blocks):
        """The direct slots, the indirect block and the double indirect
        one for a file's blocks (allocating the map's blocks)."""
        direct = blocks[:NDIRECT] + [0] * (NDIRECT - len(blocks[:NDIRECT]))
        rest = blocks[NDIRECT:]
        ind = dind = 0
        if rest:
            ind = self.alloc()
            first = rest[:PER_BLOCK]
            self.data[ind * BLOCK:ind * BLOCK + 4 * len(first)] = struct.pack(f"<{len(first)}I", *first)
            rest = rest[PER_BLOCK:]
        if rest:
            dind = self.alloc()
            slots = []
            while rest:
                b = self.alloc()
                part = rest[:PER_BLOCK]
                self.data[b * BLOCK:b * BLOCK + 4 * len(part)] = struct.pack(f"<{len(part)}I", *part)
                slots.append(b)
                rest = rest[PER_BLOCK:]
            self.data[dind * BLOCK:dind * BLOCK + 4 * len(slots)] = struct.pack(f"<{len(slots)}I", *slots)
        return direct, ind, dind

    def finish(self):
        """The image's bytes."""
        # directories' contents become files' blocks
        for ino, entries in self.dirs.items():
            raw = b"".join(struct.pack("<I28s", child, name.encode()) for name, child in entries)
            blocks = []
            for off in range(0, len(raw), BLOCK):
                b = self.alloc()
                chunk = raw[off:off + BLOCK]
                self.data[b * BLOCK:b * BLOCK + len(chunk)] = chunk
                blocks.append(b)
            self.inodes[ino][2] = len(raw)
            self.inodes[ino][4] = blocks
        for ino, (mode, nlink, size, mtime, blocks) in self.inodes.items():
            if mode & 0xF000 == S_IFCHR:
                direct, ind, dind = blocks + [0] * (NDIRECT - len(blocks)), 0, 0
            else:
                direct, ind, dind = self._block_map(blocks)
            raw = struct.pack("<HHII11III", mode, nlink, size, mtime, *direct, ind, dind)
            at = (self.inode_start + ino // INODES_PER_BLOCK) * BLOCK + (ino % INODES_PER_BLOCK) * 64
            self.data[at:at + 64] = raw
        # the bitmap: everything up to next_block is in use
        for b in range(self.next_block):
            byte = self.bitmap_start * BLOCK + b // 8
            self.data[byte] |= 1 << (b % 8)
        sb = struct.pack("<10I", MAGIC, 1, self.nblocks, self.ninodes, self.bitmap_start,
                         self.bitmap_blocks, self.inode_start, self.inode_blocks, self.data_start,
                         self.now)
        self.data[BLOCK:BLOCK + len(sb)] = sb
        return bytes(self.data)


def make(files, size=8 << 20, ninodes=1024, dirs=(), devices=None, now=None):
    """An image with files {path: bytes} and empty directories `dirs`, and
    /dev's devices."""
    img = Image(size, ninodes, now)
    for d in dirs:
        img.mkdir(d)
    for kind in (devices if devices is not None else DEVICES):
        img.add_device(f"/dev/{kind}", kind)
    for path in sorted(files):
        img.add_file(path, files[path])
    return img.finish()


class Reader:
    """An image read back: for tests, to see what the machine wrote."""

    def __init__(self, data):
        self.data = data
        f = struct.unpack_from("<10I", data, BLOCK)
        if f[0] != MAGIC:
            raise FsError("not a Fen file system")
        (_, _, self.nblocks, self.ninodes, self.bitmap_start, _, self.inode_start, _,
         self.data_start, _) = f

    def inode(self, ino):
        at = (self.inode_start + ino // INODES_PER_BLOCK) * BLOCK + (ino % INODES_PER_BLOCK) * 64
        v = struct.unpack_from("<HHII11III", self.data, at)
        return {"mode": v[0], "nlink": v[1], "size": v[2], "mtime": v[3],
                "direct": list(v[4:15]), "indirect": v[15], "dindirect": v[16]}

    def _block(self, ino, bn):
        i = self.inode(ino)
        if bn < NDIRECT:
            return i["direct"][bn]
        bn -= NDIRECT
        if bn < PER_BLOCK:
            if not i["indirect"]:
                return 0
            return struct.unpack_from("<I", self.data, i["indirect"] * BLOCK + 4 * bn)[0]
        bn -= PER_BLOCK
        if not i["dindirect"]:
            return 0
        mid = struct.unpack_from("<I", self.data, i["dindirect"] * BLOCK + 4 * (bn // PER_BLOCK))[0]
        if not mid:
            return 0
        return struct.unpack_from("<I", self.data, mid * BLOCK + 4 * (bn % PER_BLOCK))[0]

    def read_inode(self, ino):
        size = self.inode(ino)["size"]
        out = bytearray()
        for bn in range((size + BLOCK - 1) // BLOCK):
            b = self._block(ino, bn)
            out += self.data[b * BLOCK:(b + 1) * BLOCK] if b else bytes(BLOCK)
        return bytes(out[:size])

    def listdir_ino(self, ino):
        raw = self.read_inode(ino)
        out = []
        for off in range(0, len(raw), 32):
            child, name = struct.unpack_from("<I28s", raw, off)
            if child:
                out.append((name.split(b"\0")[0].decode(), child))
        return out

    def lookup(self, path):
        ino = ROOT
        for part in [p for p in path.split("/") if p]:
            for name, child in self.listdir_ino(ino):
                if name == part:
                    ino = child
                    break
            else:
                raise FsError(f"{path}: not found")
        return ino

    def listdir(self, path):
        return sorted(n for n, _ in self.listdir_ino(self.lookup(path)) if n not in (".", ".."))

    def read(self, path):
        return self.read_inode(self.lookup(path))
