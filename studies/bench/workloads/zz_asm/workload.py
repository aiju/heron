TITLE = "smoke test"
PART = "asm"
CATEGORY = "test"
SOURCES = ["main.s"]
SIZES = {"test": {"N": 3}, "ref": {"N": 10}}
def data(p): return {"blob": bytes(range(p["N"]))}
def reference(p):
    h = 5381
    for b in bytes(range(p["N"])): h = ((h * 33) ^ b) & 0xFFFFFFFF
    return f"hash {h:08x}\n".encode()
