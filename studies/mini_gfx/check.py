"""The library's checks (heron mini_gfx check): the self-test in every
kernel variant, and every mode, layout and F1 setting against the
video's decoder (the simulator's frames)."""

from . import programs

MODE_BPP = [4, 8, 8, 2, 1, 2, 1]


def selftest(variant):
    r = programs.get("check/selftest").run(variant=variant)
    return "selftest ok" in r.output, r.output.strip().splitlines()[-1] if r.output else r.trap


def modes():
    """[(layout, mode, f1, bad pixels)] for every combination."""
    p = programs.get("check/modes")
    out = []
    for layout in ("L0", "L1"):
        for mode in range(7):
            for f1 in (0, 1):
                if f1 and (layout == "L1" or mode in (0, 1, 2)):
                    continue
                r = p.run(layout=layout, pokes={"_test_mode": mode, "_test_f1": f1})
                if "modes" not in r.shots:
                    out.append((layout, mode, f1, -1))
                    continue
                w, h, data = r.shots["modes"]
                px = memoryview(data).cast("H")
                bpp = MODE_BPP[mode]
                bad = 0
                for y in range(0, h, 7):
                    for x in range(0, w, 3):
                        lx = x // 2 if mode == 1 else x
                        if px[y * w + x] != (7 * lx + 3 * y) & ((1 << bpp) - 1):
                            bad += 1
                out.append((layout, mode, f1, bad))
    return out


def main():
    ok = True
    for v in ("c", "asm", "blk", "wif"):
        good, last = selftest(v)
        print(f"selftest {v:3s}: {last}")
        ok &= good
    for layout, mode, f1, bad in modes():
        print(f"{layout} M{mode}{' F1' if f1 else '   '}: "
              f"{'ok' if bad == 0 else 'no picture' if bad < 0 else f'{bad} pixels differ'}")
        ok &= bad == 0
    return 0 if ok else 1
