"""The opcode map as a page: the explorer (opcode-map.html) with a map
built in, RFC 0028's unless told otherwise."""

import hashlib
import json
import os
import subprocess

from heron import ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "opcode-map.html")
MAP = os.path.join(ROOT, "reports", "0028-rfc-draft-2-isa", "map.json")
SLOT = '<script type="application/json" id="heron-map">null</script>'


def last_change(path):
    """The short hash and date of the commit that last changed a file, or
    None outside a checkout or for a file git doesn't know."""
    r = subprocess.run(["git", "log", "-1", "--format=%h %cs", "--", os.path.relpath(path, ROOT)],
                       cwd=ROOT, capture_output=True, text=True)
    out = r.stdout.split() if r.returncode == 0 else []
    return (out[0], out[1]) if len(out) == 2 else None


def bundle(path=MAP):
    """What the page is built with: the exported map, a name for it, where it
    came from, and a stamp that changes when the map does."""
    with open(path, "rb") as f:
        raw = f.read()
    exported = json.loads(raw)
    if exported.get("format") != "heron-opcode-map" or "state" not in exported:
        raise ValueError(f"{path}: not an exported opcode map")
    source = os.path.relpath(os.path.abspath(path), ROOT)
    change = last_change(path)
    name = "RFC 0028" if os.path.abspath(path) == MAP else exported.get("name") or "Map"
    return {
        "name": f"{name} ({change[0]})" if change else name,
        "source": f"{source} at {change[0]}, {change[1]}" if change else source,
        "stamp": hashlib.sha256(raw).hexdigest()[:16],
        "map": exported,
    }


def page(path=MAP):
    """The explorer with a map built in, as one HTML file."""
    with open(SOURCE) as f:
        html = f.read()
    if html.count(SLOT) != 1:
        raise RuntimeError(f"{SOURCE}: expected one {SLOT}")
    # Inside a script element, only "</" could end it early.
    data = json.dumps(bundle(path), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return html.replace(SLOT, SLOT.replace(">null<", f">{data}<"))


def write(out, path=MAP):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        f.write(page(path))
    return out
