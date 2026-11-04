/* An inventory's data work, as Heron Mini's forms application does it
   (studies/mini_gfx/apps/forms on the claude/trusting-fermi-7diz0f
   branch) for a workshop's parts store: tables read from CSV, indexed by
   key in hash tables, joined, aggregated, sorted and searched, and a
   report printed from them. */

#ifndef DB_H
#define DB_H

#define NCAT 8
#define MAXFIELDS 12

/* ---- CSV (csv.c) ---- */

typedef struct {
    const char *s, *end;        /* the text not read yet */
    int line;                   /* the record's line, from 1 */
    char rec[512];              /* the record's fields, each ending in a NUL */
    char *field[MAXFIELDS];
    int nfield;
} Csv;

void csv_open(Csv *c, const unsigned char *text, unsigned n);
/* the next record's fields into c->field: how many, 0 at the end */
int csv_next(Csv *c);
/* a field as a whole number (a sign allowed): 1 if it is one */
int csv_int(const char *s, int *v);
/* a field as an amount of money, "12.34", in pence: 1 if it is one */
int csv_money(const char *s, int *v);
/* a copy of s in memory of its own */
char *xstrdup(const char *s);

/* ---- the tables (inventory.c) ---- */

typedef struct {
    int id;
    char *name, *city;
    int lead, rating;           /* days to deliver; 1 to 5 stars */
    /* the joins' totals */
    int nparts, nmoves, nlow;
    unsigned value;             /* the stock it supplied, in pence */
    int next;                   /* the id index's chain */
} Supplier;

#define F_HAZARD 1              /* stored apart */
#define F_DISCONT 2             /* discontinued: not reordered */

typedef struct {
    char code[12];              /* FA-1042: the key */
    char bin[8];                /* A07-3 */
    char *desc;
    char *lower;                /* desc in lower case, for the search */
    int cat, unit, flags;
    int sup;                    /* the supplier, an index into sups[]; -1 if unknown */
    int qty, reorder, price;    /* price in pence */
    /* the movements' totals */
    int in, out, adj, nmoves;
    int next;                   /* the code index's chain */
} Part;

extern Part *parts;
extern int nparts;
extern Supplier *sups;
extern int nsups;
extern const char *const cat_names[NCAT];
extern const char *const unit_names[];

/* lines that couldn't be used, by why */
extern int bad_fields, bad_number, bad_code, bad_supplier;
/* the movements by month: units in and out, adjustments, lines */
extern int month_in[12], month_out[12], month_adj[12], month_lines[12];
extern int moves_used;

void load_suppliers(const unsigned char *text, unsigned n);
void load_parts(const unsigned char *text, unsigned n);
void load_moves(const unsigned char *text, unsigned n);
int part_find(const char *code);        /* by code: its index, or -1 */
int supplier_find(int id);

/* stock now, and its value in pence */
int on_hand(const Part *p);
unsigned value(const Part *p);

/* ---- the report (report.c) ---- */

void report_all(void);
extern char *report;
extern int report_len;
extern int n_reorder, n_matches;

#endif
