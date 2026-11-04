/* The tables (db.h): suppliers and parts read from CSV into arrays,
   indexed by key in hash tables with chains, and the stock movements
   joined to the parts by code and summed into them, their suppliers and
   the months. A line that can't be used is counted by why and skipped. */

#include <stdlib.h>
#include <string.h>
#include "db.h"

Part *parts;
int nparts;
Supplier *sups;
int nsups;
int bad_fields, bad_number, bad_code, bad_supplier;
int month_in[12], month_out[12], month_adj[12], month_lines[12];
int moves_used;

const char *const cat_names[NCAT] = {
    "Fasteners", "Bearings", "Electrical", "Fluid power", "Abrasives", "Drive parts",
    "Chemicals", "Cutting tools",
};
const char *const unit_names[] = {"each", "pack", "m", "kg", "l", 0};

/* the indexes: a power of two of chains, each through the records' next */
#define NHASH 512
static int part_hash[NHASH], sup_hash[NHASH];

/* FNV-1a */
static unsigned hash_str(const char *s)
{
    unsigned h = 2166136261u;
    while (*s)
        h = (h ^ (unsigned char)*s++) * 16777619u;
    return h;
}

/* the records a table's text has: its lines, less the header */
static int count_records(const unsigned char *text, unsigned n)
{
    int k = 0;
    unsigned i;
    for (i = 0; i < n; i++)
        k += text[i] == '\n';
    return k > 0 ? k - 1 : 0;
}

/* a name's place in a list ending in 0, or -1 */
static int lookup(const char *const *names, const char *s)
{
    int i;
    for (i = 0; names[i]; i++)
        if (!strcmp(names[i], s))
            return i;
    return -1;
}

static int cat_of(const char *s)
{
    int i;
    for (i = 0; i < NCAT; i++)
        if (!strcmp(cat_names[i], s))
            return i;
    return -1;
}

int part_find(const char *code)
{
    int i = part_hash[hash_str(code) & (NHASH - 1)];
    while (i >= 0 && strcmp(parts[i].code, code))
        i = parts[i].next;
    return i;
}

int supplier_find(int id)
{
    int i = sup_hash[(unsigned)id * 2654435761u >> 23 & (NHASH - 1)];
    while (i >= 0 && sups[i].id != id)
        i = sups[i].next;
    return i;
}

int on_hand(const Part *p)
{
    return p->qty + p->in - p->out + p->adj;
}

unsigned value(const Part *p)
{
    int n = on_hand(p);
    return n > 0 ? (unsigned)n * p->price : 0;
}

/* suppliers.csv: id,name,city,lead_days,rating */
void load_suppliers(const unsigned char *text, unsigned n)
{
    Csv c;
    int k;
    sups = calloc(count_records(text, n) + 1, sizeof(Supplier));
    for (k = 0; k < NHASH; k++)
        sup_hash[k] = -1;
    csv_open(&c, text, n);
    csv_next(&c);               /* the header */
    while (csv_next(&c)) {
        Supplier *s = &sups[nsups];
        unsigned h;
        if (c.nfield != 5) {
            bad_fields++;
            continue;
        }
        if (!csv_int(c.field[0], &s->id) || !csv_int(c.field[3], &s->lead) ||
            !csv_int(c.field[4], &s->rating)) {
            bad_number++;
            continue;
        }
        s->name = xstrdup(c.field[1]);
        s->city = xstrdup(c.field[2]);
        h = (unsigned)s->id * 2654435761u >> 23 & (NHASH - 1);
        s->next = sup_hash[h];
        sup_hash[h] = nsups++;
    }
}

/* parts.csv: code,description,category,supplier,bin,qty,reorder,price,unit,flags */
void load_parts(const unsigned char *text, unsigned n)
{
    Csv c;
    int k, sid;
    char *d;
    parts = calloc(count_records(text, n) + 1, sizeof(Part));
    for (k = 0; k < NHASH; k++)
        part_hash[k] = -1;
    csv_open(&c, text, n);
    csv_next(&c);
    while (csv_next(&c)) {
        Part *p = &parts[nparts];
        unsigned h;
        const char *f;
        if (c.nfield != 10 || strlen(c.field[0]) >= sizeof p->code ||
            strlen(c.field[4]) >= sizeof p->bin) {
            bad_fields++;
            continue;
        }
        if (!csv_int(c.field[3], &sid) || !csv_int(c.field[5], &p->qty) ||
            !csv_int(c.field[6], &p->reorder) || !csv_money(c.field[7], &p->price)) {
            bad_number++;
            continue;
        }
        strcpy(p->code, c.field[0]);
        strcpy(p->bin, c.field[4]);
        p->desc = xstrdup(c.field[1]);
        p->lower = xstrdup(c.field[1]);
        for (d = p->lower; *d; d++)
            if ((unsigned)(*d - 'A') < 26)
                *d += 32;
        p->cat = cat_of(c.field[2]);
        p->unit = lookup(unit_names, c.field[8]);
        for (f = c.field[9]; *f; f++)
            p->flags |= *f == 'H' ? F_HAZARD : *f == 'D' ? F_DISCONT : 0;
        /* the join to the supplier, once */
        p->sup = supplier_find(sid);
        if (p->sup < 0 || p->cat < 0)
            bad_supplier++;
        h = hash_str(p->code) & (NHASH - 1);
        p->next = part_hash[h];
        part_hash[h] = nparts++;
    }
}

/* moves.csv: date,code,qty,kind,ref; each joined to its part by code */
void load_moves(const unsigned char *text, unsigned n)
{
    Csv c;
    int i, q, month;
    csv_open(&c, text, n);
    csv_next(&c);
    while (csv_next(&c)) {
        Part *p;
        const char *kind;
        if (c.nfield != 5 || strlen(c.field[0]) != 10) {
            bad_fields++;
            continue;
        }
        month = (unsigned)strtoul(c.field[0] + 5, 0, 10) - 1;
        if (!csv_int(c.field[2], &q) || month < 0 || month >= 12) {
            bad_number++;
            continue;
        }
        if ((i = part_find(c.field[1])) < 0) {
            bad_code++;
            continue;
        }
        p = &parts[i];
        kind = c.field[3];
        if (!strcmp(kind, "IN")) {
            p->in += q;
            month_in[month] += q;
        } else if (!strcmp(kind, "OUT")) {
            p->out += q;
            month_out[month] += q;
        } else {
            p->adj += q;
            month_adj[month]++;
        }
        p->nmoves++;
        month_lines[month]++;
        if (p->sup >= 0)
            sups[p->sup].nmoves++;
        moves_used++;
    }
}
