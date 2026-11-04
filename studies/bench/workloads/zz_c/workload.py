TITLE = "smoke test"
PART = "c"
CATEGORY = "test"
SOURCES = ["main.c"]
SIZES = {"test": {"N": 3}, "ref": {"N": 10}}
def data(p): return {"blob": bytes(range(p["N"]))}
