/* The report (db.h): the stock by category, what to reorder from whom,
   the most valuable stock, searches of the descriptions, the suppliers'
   totals, the movements by month and the first page of the full
   listing. Each section's rows are picked, sorted with qsort and printed
   with sprintf into one buffer in columns, as a report writer prints
   for a line printer.

   Every comparison ends on the part's code, or the supplier's id, which
   are unique: no two rows tie, so the order doesn't depend on qsort. */

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "db.h"

#define REPORT_MAX 65536
#define WIDTH 78

char *report;
int report_len;
int n_reorder, n_matches;

static void out(const char *fmt, ...)
{
    va_list ap;
    if (report_len > REPORT_MAX - 256)
        return;
    va_start(ap, fmt);
    report_len += vsprintf(report + report_len, fmt, ap);
    va_end(ap);
}

static void rule(int c)
{
    char line[WIDTH + 2];
    memset(line, c, WIDTH);
    line[WIDTH] = '\n';
    line[WIDTH + 1] = 0;
    out("%s", line);
}

static void heading(const char *title)
{
    out("\n%s\n", title);
    rule('=');
}

/* pence as pounds with thousands separated: "12,345.67". Written from
   the right, a digit at a time. */
static char *money(char *buf, unsigned pence)
{
    char t[24];
    unsigned u = pence / 100, c = pence % 100;
    int n = 0, k = 0;
    t[n++] = '0' + c % 10;
    t[n++] = '0' + c / 10;
    t[n++] = '.';
    do {
        if (k > 0 && k % 3 == 0)
            t[n++] = ',';
        t[n++] = '0' + u % 10;
        u /= 10;
        k++;
    } while (u);
    for (k = 0; k < n; k++)
        buf[k] = t[n - 1 - k];
    buf[n] = 0;
    return buf;
}

static const char *supplier_name(const Part *p)
{
    return p->sup >= 0 ? sups[p->sup].name : "(unknown)";
}

/* ---- the comparisons ---- */

static int by_code(const Part *a, const Part *b)
{
    return strcmp(a->code, b->code);
}

/* the reorder list: by supplier, then code */
static int cmp_reorder(const void *x, const void *y)
{
    const Part *a = *(Part *const *)x, *b = *(Part *const *)y;
    int c = strcmp(supplier_name(a), supplier_name(b));
    return c ? c : by_code(a, b);
}

/* the most valuable first */
static int cmp_value(const void *x, const void *y)
{
    const Part *a = *(Part *const *)x, *b = *(Part *const *)y;
    unsigned va = value(a), vb = value(b);
    if (va != vb)
        return va > vb ? -1 : 1;
    return by_code(a, b);
}

/* by description, without case */
static int cmp_desc(const void *x, const void *y)
{
    const Part *a = *(Part *const *)x, *b = *(Part *const *)y;
    int c = strcmp(a->lower, b->lower);
    return c ? c : by_code(a, b);
}

/* the listing: by category, description, code */
static int cmp_listing(const void *x, const void *y)
{
    const Part *a = *(Part *const *)x, *b = *(Part *const *)y;
    if (a->cat != b->cat)
        return a->cat - b->cat;
    return cmp_desc(x, y);
}

static int cmp_supplier(const void *x, const void *y)
{
    const Supplier *a = *(Supplier *const *)x, *b = *(Supplier *const *)y;
    if (a->value != b->value)
        return a->value > b->value ? -1 : 1;
    return a->id - b->id;
}

/* ---- the sections ---- */

static void by_category(void)
{
    int count[NCAT], units[NCAT], lo[NCAT], hi[NCAT], c, i;
    unsigned val[NCAT], sum[NCAT], total = 0;
    char m1[20], m2[20], m3[20], m4[20];
    heading("Stock by category");
    out("%-14s %6s %8s %14s %10s %10s %10s\n", "Category", "Parts", "Units", "Value", "Lowest",
        "Highest", "Average");
    rule('-');
    for (c = 0; c < NCAT; c++) {
        count[c] = units[c] = 0;
        val[c] = sum[c] = 0;
        lo[c] = 0x7fffffff;
        hi[c] = 0;
    }
    for (i = 0; i < nparts; i++) {
        const Part *p = &parts[i];
        if (p->cat < 0)
            continue;
        c = p->cat;
        count[c]++;
        units[c] += on_hand(p);
        val[c] += value(p);
        sum[c] += p->price;
        if (p->price < lo[c])
            lo[c] = p->price;
        if (p->price > hi[c])
            hi[c] = p->price;
    }
    for (c = 0; c < NCAT; c++) {
        if (!count[c])
            continue;
        out("%-14s %6d %8d %14s %10s %10s %10s\n", cat_names[c], count[c], units[c],
            money(m1, val[c]), money(m2, lo[c]), money(m3, hi[c]), money(m4, sum[c] / count[c]));
        total += val[c];
    }
    rule('-');
    out("%-14s %6d %8s %14s\n", "Total", nparts, "", money(m1, total));
}

static void reorder(Part **v)
{
    int i, n = 0;
    char m[20];
    heading("To reorder: below the reorder level, not discontinued");
    for (i = 0; i < nparts; i++)
        if (on_hand(&parts[i]) < parts[i].reorder && !(parts[i].flags & F_DISCONT))
            v[n++] = &parts[i];
    qsort(v, n, sizeof *v, cmp_reorder);
    out("%-22s %-8s %-28s %5s %5s %4s %9s\n", "Supplier", "Code", "Description", "Have", "Level",
        "Days", "Price");
    rule('-');
    for (i = 0; i < n; i++) {
        const Part *p = v[i];
        if (p->sup >= 0)
            sups[p->sup].nlow++;
        out("%-22.22s %-8s %-28.28s %5d %5d %4d %9s\n", supplier_name(p), p->code, p->desc,
            on_hand(p), p->reorder, p->sup >= 0 ? sups[p->sup].lead : 0, money(m, p->price));
    }
    out("%d to reorder\n", n);
    n_reorder = n;
}

static void top_value(Part **v, int top)
{
    int i;
    char m1[20], m2[20];
    heading("The most valuable stock");
    for (i = 0; i < nparts; i++)
        v[i] = &parts[i];
    qsort(v, nparts, sizeof *v, cmp_value);
    for (i = 0; i < top && i < nparts; i++) {
        const Part *p = v[i];
        out("%3d. %-8s %-36.36s %5d %-4s x %8s = %12s\n", i + 1, p->code, p->desc, on_hand(p),
            unit_names[p->unit >= 0 ? p->unit : 0], money(m1, p->price), money(m2, value(p)));
    }
}

/* the parts whose description has q in it, without case */
static void search(Part **v, const char *q)
{
    char lq[40];
    int i, n = 0;
    for (i = 0; q[i] && i < (int)sizeof lq - 1; i++)
        lq[i] = (unsigned)(q[i] - 'A') < 26 ? q[i] + 32 : q[i];
    lq[i] = 0;
    for (i = 0; i < nparts; i++)
        if (strstr(parts[i].lower, lq))
            v[n++] = &parts[i];
    qsort(v, n, sizeof *v, cmp_desc);
    out("\"%s\": %d\n", q, n);
    for (i = 0; i < n && i < 4; i++)
        out("    %-8s %-40s %-6s %s\n", v[i]->code, v[i]->desc, v[i]->bin,
            v[i]->flags & F_HAZARD ? "hazardous" : "");
    n_matches += n;
}

static const char *const queries[] = {
    "bolt", "M8", "disc", "valve", "bearing 62", "x 1", "Scotch", "belt",
};

static void suppliers(void)
{
    Supplier **v = malloc(nsups * sizeof *v);
    int i;
    char m[20];
    heading("Suppliers by the value of their stock");
    for (i = 0; i < nparts; i++)
        if (parts[i].sup >= 0) {
            sups[parts[i].sup].nparts++;
            sups[parts[i].sup].value += value(&parts[i]);
        }
    for (i = 0; i < nsups; i++)
        v[i] = &sups[i];
    qsort(v, nsups, sizeof *v, cmp_supplier);
    out("%4s %-24s %-9s %5s %5s %5s %14s %s\n", "Id", "Name", "City", "Parts", "Low", "Moves",
        "Value", "Rating");
    rule('-');
    for (i = 0; i < nsups; i++) {
        const Supplier *s = v[i];
        out("%4d %-24.24s %-9s %5d %5d %5d %14s %.*s\n", s->id, s->name, s->city, s->nparts,
            s->nlow, s->nmoves, money(m, s->value), s->rating, "*****");
    }
    free(v);
}

static void months(void)
{
    static const char *const names[12] = {"Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul",
                                          "Aug", "Sep", "Oct", "Nov", "Dec"};
    int i, lines = 0;
    heading("Movements by month");
    out("%-5s %6s %8s %8s %6s\n", "Month", "Lines", "In", "Out", "Adj");
    for (i = 0; i < 12; i++) {
        if (!month_lines[i])
            continue;
        out("%-5s %6d %8d %8d %6d\n", names[i], month_lines[i], month_in[i], month_out[i],
            month_adj[i]);
        lines += month_lines[i];
    }
    out("%d lines used; %d with fields missing, %d with bad numbers, %d with unknown codes\n",
        lines, bad_fields, bad_number, bad_code);
}

static void listing(Part **v, int page)
{
    int i, cat = -1;
    char m[20];
    heading("Parts by category (first page)");
    for (i = 0; i < nparts; i++)
        v[i] = &parts[i];
    qsort(v, nparts, sizeof *v, cmp_listing);
    for (i = 0; i < page && i < nparts; i++) {
        const Part *p = v[i];
        if (p->cat != cat) {
            cat = p->cat;
            out("%s\n", cat >= 0 ? cat_names[cat] : "?");
        }
        out("  %-8s %-34.34s %-6s %5d %9s %c%c\n", p->code, p->desc, p->bin, on_hand(p),
            money(m, p->price), p->flags & F_HAZARD ? 'H' : ' ', p->flags & F_DISCONT ? 'D' : ' ');
    }
}

/* the sections, those in SECTIONS (workload.py's size), a bit each */
void report_all(void)
{
    Part **v = malloc((nparts + 1) * sizeof *v);
    int i;
    report = malloc(REPORT_MAX);
    report_len = 0;
    out("WORKSHOP STORES: STOCK REPORT\n");
    out("%d parts from %d suppliers, %d movements\n", nparts, nsups, moves_used);
    if (SECTIONS & 1)
        by_category();
    if (SECTIONS & 2)
        reorder(v);
    if (SECTIONS & 4)
        top_value(v, TOP);
    if (SECTIONS & 8) {
        heading("Searches");
        for (i = 0; i < QUERIES && i < (int)(sizeof queries / sizeof queries[0]); i++)
            search(v, queries[i]);
    }
    if (SECTIONS & 16)
        suppliers();
    if (SECTIONS & 32)
        months();
    if (SECTIONS & 64)
        listing(v, PAGE);
    free(v);
}
