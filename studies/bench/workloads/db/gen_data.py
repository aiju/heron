"""The tables the inventory works on, made up by a deterministic
generator in the manner of Heron Mini's forms application (its data.c):
a workshop's parts, their suppliers, and a few months of stock movements.

They are CSV as a spreadsheet would export it: a header line, fields
separated by commas, text with a comma in it in double quotes (a quote in
it doubled). A few movement lines are damaged, as real exports are: a
field missing, a code that names no part, a quantity that isn't a number.
"""


class Rng:
    """Numerical Recipes' LCG, the top 24 bits used."""

    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def next(self):
        self.s = (self.s * 1664525 + 1013904223) & 0xFFFFFFFF
        return self.s >> 8

    def below(self, n):
        return self.next() % n

    def pick(self, seq):
        return seq[self.below(len(seq))]


CATEGORIES = [("FA", "Fasteners"), ("BR", "Bearings"), ("EL", "Electrical"),
              ("FP", "Fluid power"), ("AB", "Abrasives"), ("DR", "Drive parts"),
              ("CH", "Chemicals"), ("CT", "Cutting tools")]
UNITS = ["each", "pack", "m", "kg", "l"]
TOWNS = ["Ashdown", "Brockley", "Carrow", "Dunmore", "Elstow", "Fenwick", "Glenmore",
         "Hartwell", "Ironbridge", "Kestrel", "Lanyon", "Marsden", "Norwood", "Oakham",
         "Penrith", "Quarrington", "Redbourn", "Selsey", "Thornbury", "Upwell"]
TRADES = ["Fixings", "Bearings", "Electric", "Fluid", "Abrasives", "Drives", "Chemical",
          "Tooling", "Supply", "Industrial", "Trade", "Engineering"]
CITIES = ["Leeds", "Derby", "Bristol", "Norwich", "Hull", "York", "Bath", "Stoke"]
M = [3, 4, 5, 6, 8, 10, 12, 16]
LENGTHS = [10, 12, 16, 20, 25, 30, 35, 40, 50, 60, 80]
FINISH = ["zinc", "A2 stainless", "8.8 black", "A4 stainless"]
THREADS = ["1/8", "1/4", "3/8", "1/2", "3/4"]
GRITS = [40, 60, 80, 120, 180, 240]


def describe(r, cat):
    """A description, a unit and a price in pence for a part of category cat."""
    t = r.below(8)
    m = r.pick(M)
    if cat == 0:
        d = [f"Hex bolt M{m} x {r.pick(LENGTHS)}, {r.pick(FINISH)}",
             f"Socket cap screw M{m} x {r.pick(LENGTHS)}", f"Nyloc nut M{m}, {r.pick(FINISH)}",
             f"Flat washer M{m}", f"Spring washer M{m}", f"Threaded rod M{m} x 1 m",
             f"Blind rivet {r.pick(['4.0', '4.8'])} x {8 + 2 * r.below(8)}",
             f"Wing nut M{m}"][t]
        return d, "pack", 120 + r.below(1800)
    if cat == 1:
        d = [f"Ball bearing 62{r.below(12):02d}-2RS", f"Ball bearing 60{r.below(12):02d}-ZZ",
             f"Pillow block UCP2{4 + r.below(8):02d}", f"Needle roller HK{8 + 2 * r.below(8):02d}10",
             f"Bronze bush {8 + 2 * r.below(10)} x {14 + 2 * r.below(10)}",
             f"Thrust bearing 511{r.below(12):02d}", f"Circlip, external, {10 + 2 * r.below(20)} mm",
             f"Oil seal {15 + 5 * r.below(8)} x {30 + 5 * r.below(10)} x 7"][t]
        return d, "each", 180 + r.below(4500)
    if cat == 2:
        d = [f"Fuse {1 << r.below(6)}A time-delay", f"Relay 24 V DC {1 + r.below(4)}-pole",
             f"Contactor {9 + 3 * r.below(10)} A", f"Terminal block {2 + 2 * r.below(6)}-way",
             f"Cable gland M{12 + 4 * r.below(6)}", f"Flex cable {2 + r.below(4)}-core 1.5 mm2",
             f"Proximity sensor M{8 + 4 * r.below(4)} PNP",
             f"Push button, {r.pick(['green', 'red', 'yellow', 'black'])}"][t]
        return d, "m" if t == 5 else "each", 50 + r.below(3000)
    if cat == 3:
        d = [f"O-ring {5 + 2 * r.below(30)} x {1 + r.below(4)} NBR",
             f"Push-in fitting {4 + 2 * r.below(5)} mm", f"Air hose {4 + 2 * r.below(5)} mm PU",
             f"Ball valve G{r.pick(THREADS)}", f"Solenoid valve 5/2 G{r.pick(THREADS)}",
             f"Pressure gauge 0-{6 + 10 * r.below(25)} bar",
             f"Cylinder {16 + 4 * r.below(10)} x {25 * (1 + r.below(8))} stroke",
             f"Filter regulator G{r.pick(THREADS)}"][t]
        return d, "m" if t == 2 else "each", 90 + r.below(9000)
    if cat == 4:
        d = [f"Flap disc {r.pick([115, 125])} mm P{r.pick(GRITS)}",
             f"Cutting disc {r.pick([115, 125, 230])} x 1.0 mm",
             f"Grinding disc {r.pick([115, 125, 230])} x 6 mm",
             f"Sanding belt {50 + 25 * r.below(4)} x {450 + 100 * r.below(8)} P{r.pick(GRITS)}",
             f"Wire cup brush {60 + 10 * r.below(5)} mm",
             f"Abrasive roll {25 + 25 * r.below(4)} mm P{r.pick(GRITS)}",
             f"Flap wheel {40 + 10 * r.below(5)} x 20, P{r.pick(GRITS)}",
             f"\"Scotch\" pad, {r.pick(['fine', 'medium', 'coarse'])}"][t]
        return d, "m" if t == 5 else "each", 60 + r.below(1500)
    if cat == 5:
        d = [f"V-belt SPZ {600 + 25 * r.below(60)}", f"V-belt A{30 + r.below(40)}",
             f"Roller chain {6 + 2 * r.below(6)}B-1", f"Sprocket {6 + 2 * r.below(6)}B {9 + r.below(30)}T",
             f"Timing belt HTD {300 + 5 * r.below(200)}-5M", f"Jaw coupling {10 + 2 * r.below(15)} mm",
             f"Key steel {4 + 2 * r.below(5)} x {4 + 2 * r.below(5)} x 1 m",
             f"Gearbox, worm, {5 * (1 + r.below(12))}:1"][t]
        return d, "m" if t == 2 else "each", 250 + r.below(6000)
    if cat == 6:
        d = [f"Threadlocker, medium, {10 << r.below(3)} ml", f"Lithium grease {400 << r.below(2)} g",
             f"Cutting fluid {1 + 4 * r.below(3)} l", f"Degreaser spray {400 + 100 * r.below(2)} ml",
             f"Epoxy, two-part, {25 + 25 * r.below(3)} ml", f"Hydraulic oil HLP {32 + 14 * r.below(3)}",
             f"Anti-seize paste {100 << r.below(3)} g", f"Contact cleaner {200 << r.below(2)} ml"][t]
        return d, "l" if t in (2, 5) else "each", 300 + r.below(2500)
    d = [f"HSS drill {1 + r.below(12)}.{5 * r.below(2)} mm", f"Cobalt drill {2 + r.below(10)} mm",
         f"Machine tap M{m}", f"End mill {3 + r.below(14)} mm 4-flute",
         f"Hole saw {16 + 3 * r.below(30)} mm", f"Hacksaw blade {18 + 6 * r.below(3)} tpi",
         f"Countersink {6 + 2 * r.below(8)} mm, 90 deg", f"Reamer H7 {3 + r.below(18)} mm"][t]
    return d, "each", 200 + r.below(5000)


def csv_field(s):
    """A field as a spreadsheet writes it: quoted if it has a comma or a quote."""
    if "," in s or '"' in s:
        return '"' + s.replace('"', '""') + '"'
    return s


def tables(nparts, nmoves, nsup):
    """The three tables as CSV text: parts, suppliers, movements."""
    r = Rng(0x464F524D)
    sup = ["id,name,city,lead_days,rating"]
    names = set()
    for i in range(nsup):
        name = f"{r.pick(TOWNS)} {r.pick(TRADES)}"
        while name in names:
            name = f"{r.pick(TOWNS)} {r.pick(TRADES)}"
        names.add(name)
        sup.append(f"{101 + 7 * i},{csv_field(name + ', Ltd' if r.below(3) == 0 else name)},"
                   f"{r.pick(CITIES)},{2 + r.below(20)},{1 + r.below(5)}")
    parts = ["code,description,category,supplier,bin,qty,reorder,price,unit,flags"]
    codes = []
    num = [1000 + 10 * r.below(40) for _ in CATEGORIES]
    for i in range(nparts):
        c = r.below(len(CATEGORIES) + 2)
        if c >= len(CATEGORIES):
            c = 0                   # a workshop has more fasteners
        num[c] += 1 + r.below(17)
        code = f"{CATEGORIES[c][0]}-{num[c]}"
        codes.append(code)
        desc, unit, price = describe(r, c)
        reorder = 5 * (1 + r.below(20))
        qty = r.below(reorder * 4) if r.below(5) else r.below(reorder)
        flags = ("H" if c == 6 and r.below(3) else "") + ("D" if r.below(18) == 0 else "")
        supplier = 101 + 7 * (c % nsup if r.below(3) else r.below(nsup))
        parts.append(f"{code},{csv_field(desc)},{CATEGORIES[c][1]},{supplier},"
                     f"{chr(65 + c)}{1 + r.below(24):02d}-{1 + r.below(5)},{qty},{reorder},"
                     f"{price // 100}.{price % 100:02d},{unit},{flags}")
    moves = ["date,code,qty,kind,ref"]
    day = 0
    for i in range(nmoves):
        day += r.below(3)
        month, dom = 1 + day // 28 % 12, 1 + day % 28
        code = codes[min(r.below(len(codes)), r.below(len(codes)))]   # some parts move more
        kind = r.pick(["OUT", "OUT", "OUT", "IN", "ADJ"])
        q = {"OUT": 1 + r.below(12), "IN": 10 + 5 * r.below(10), "ADJ": r.below(9) - 4}[kind]
        ref = f"{'PO' if kind == 'IN' else 'WO'}{20000 + r.below(9000)}"
        line = f"2026-{month:02d}-{dom:02d},{code},{q},{kind},{ref}"
        bad = r.below(60)
        if bad == 0:
            line = f"2026-{month:02d}-{dom:02d},{code},{kind},{ref}"        # a field missing
        elif bad == 1:
            line = f"2026-{month:02d}-{dom:02d},XX-{r.below(9999)},{q},{kind},{ref}"
        elif bad == 2:
            line = f"2026-{month:02d}-{dom:02d},{code},n/a,{kind},{ref}"
        moves.append(line)
    return {"parts": ("\n".join(parts) + "\n").encode(),
            "suppliers": ("\n".join(sup) + "\n").encode(),
            "moves": ("\n".join(moves) + "\n").encode()}
