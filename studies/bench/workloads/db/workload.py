"""An inventory application's data work: a parts store's tables read from
CSV, indexed, joined, aggregated, sorted and searched, and a report
printed from them.

It stands for the business software Heron runs, Heron Mini's forms
application (its workshop parts store) behind its windows: the records
and their fields are the forms app's. Three tables (gen_data.py) come in
as CSV, as a spreadsheet exports them: parts (quoted descriptions with
commas in them), suppliers, and stock movements, a few of them damaged.
They're parsed (csv.c: fields, strtoul, money) into arrays with hash
indexes by key (inventory.c); each part is joined to its supplier by id,
each movement to its part by code and summed into it, its supplier and
its month. The report (report.c) has the stock by category (counts, sums,
lowest, highest and average prices), the reorder list joined with the
suppliers and sorted by supplier and code, the most valuable stock,
case-blind substring searches of the descriptions, the suppliers'
totals and the movements by month, and the first page of the listing by
category and description, all with qsort and tie-free comparisons, and
printed with sprintf in padded columns with money in thousands. The
report is hashed.

PARTS, MOVES and SUPPLIERS are the tables' sizes; SECTIONS the report's
sections (a bit each, all of them from `small` up), and TOP, QUERIES and PAGE how
many of the most valuable, of the searches and of the listing's lines it
has.

Where the time goes (`small`): a fifth in sprintf, formatting the report's
columns; a fifth parsing the CSV (csv_next, strtoul); an eighth sorting
(qsort, its swaps, the comparisons and their strcmp); strstr for the
searches; FNV hashing of codes for the index and the joins; and hashing
the 12 KB report for the result (about 8%).
"""

from . import gen_data

TITLE = "an inventory: CSV tables indexed, joined, sorted, searched, reported"
PART = "c"
CATEGORY = "apps"
SOURCES = ["main.c", "csv.c", "inventory.c", "report.c"]
SIZES = {"tiny": {"PARTS": 8, "MOVES": 12, "SUPPLIERS": 3, "SECTIONS": 2 | 8, "TOP": 3,
                  "QUERIES": 3, "PAGE": 4},
         "small": {"PARTS": 120, "MOVES": 300, "SUPPLIERS": 12, "SECTIONS": 127, "TOP": 12,
                 "QUERIES": 8, "PAGE": 30},
         "full": {"PARTS": 1000, "MOVES": 2500, "SUPPLIERS": 40, "SECTIONS": 127, "TOP": 20, "QUERIES": 24, "PAGE": 60}}


def data(p):
    t = gen_data.tables(p["PARTS"], p["MOVES"], p["SUPPLIERS"])
    return {"t_parts": t["parts"], "t_suppliers": t["suppliers"], "t_moves": t["moves"]}
