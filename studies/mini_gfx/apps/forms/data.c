/* The backend (data.h): the generator, the sort and the filter. The data
   is made up here: names of parts from templates per category, made-up
   suppliers, quantities and prices from a linear congruential generator,
   so every run has the same 200 records. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "data.h"

Part parts[MAXPARTS];
int nparts;
int view[MAXPARTS];
int nview, nlive;
int filter_mode = 3;
int sort_mode = 1;
unsigned filter_scanned;

static int order[MAXPARTS];     /* every live record, sorted */
static int norder;
static char last_query[40];

const char *cat_names[NCAT] = {
    "Fasteners", "Bearings", "Electrical", "Fluid power", "Abrasives", "Drive parts",
    "Chemicals", "Cutting tools",
};
const char *unit_names[NUNIT] = {"each", "pack", "m", "kg", "l"};
static const char cat_code[NCAT][3] = {"FA", "BR", "EL", "FP", "AB", "DR", "CH", "CT"};

/* invented names */
const char *suppliers[] = {
    "Ashdown Fixings", "Brockley Bearings", "Carrow Electric", "Dunmore Fluid", "Elstow Abrasives",
    "Fenwick Drives", "Glenmore Chemical", "Hartwell Tooling", "Ironbridge Supply",
    "Kestrel Industrial", "Lanyon Trade",
};
int nsuppliers = sizeof suppliers / sizeof suppliers[0];

static unsigned seed;

static int rnd(int n)
{
    seed = seed * 1103515245u + 12345u;
    return (seed >> 16 & 0x7FFF) % n;
}

static int pick(const short *v, int n)
{
    return v[rnd(n)];
}

#define PICK(a) pick(a, sizeof a / sizeof a[0])

static const short msize[] = {3, 4, 5, 6, 8, 10, 12, 16};
static const short mlen[] = {10, 12, 16, 20, 25, 30, 35, 40, 50, 60, 80};
static const short grits[] = {40, 60, 80, 120, 180, 240};
static const short discs[] = {115, 125, 180, 230};
static const char *finishes[] = {"zinc", "A2 stainless", "8.8 black", "A4 stainless"};
static const char *threads[] = {"1/8", "1/4", "3/8", "1/2", "3/4"};
static const char *colours[] = {"green", "red", "yellow", "black", "blue"};

/* a description for category c; sets the unit, the price range and flags */
static void describe(Part *p)
{
    char *d = p->desc;
    int m = PICK(msize), t = rnd(9);
    p->unit = U_EACH;
    p->price = 50 + rnd(3000);
    switch (p->cat) {
    case CAT_FASTEN:
        p->unit = U_PACK;
        p->price = 120 + rnd(1800);
        if (t == 0)
            sprintf(d, "Hex bolt M%d x %d %s", m, PICK(mlen), finishes[rnd(4)]);
        else if (t == 1)
            sprintf(d, "Socket cap screw M%d x %d", m, PICK(mlen));
        else if (t == 2)
            sprintf(d, "Countersunk screw M%d x %d", m, PICK(mlen));
        else if (t == 3)
            sprintf(d, "Nyloc nut M%d %s", m, finishes[rnd(4)]);
        else if (t == 4)
            sprintf(d, "Flat washer M%d %s", m, finishes[rnd(4)]);
        else if (t == 5)
            sprintf(d, "Spring washer M%d", m);
        else if (t == 6) {
            sprintf(d, "Threaded rod M%d x 1 m", m);
            p->unit = U_EACH;
        } else if (t == 7)
            sprintf(d, "Blind rivet %s x %d", rnd(2) ? "4.0" : "4.8", 8 + 2 * rnd(8));
        else
            sprintf(d, "Wing nut M%d", m);
        break;
    case CAT_BEARING:
        if (t == 0 || t == 1)
            sprintf(d, "Ball bearing 6%d%02d-%s", t ? 0 : 2, rnd(12), rnd(2) ? "2RS" : "ZZ");
        else if (t == 2)
            sprintf(d, "Pillow block UCP2%02d", 4 + rnd(8));
        else if (t == 3)
            sprintf(d, "Needle roller HK%02d%02d", 8 + 2 * rnd(8), 10 + 2 * rnd(5));
        else if (t == 4)
            sprintf(d, "Bronze bush %d x %d x %d", 8 + 2 * rnd(10), 12 + 2 * rnd(12),
                    10 + 5 * rnd(5));
        else if (t == 5)
            sprintf(d, "Thrust bearing 511%02d", rnd(12));
        else if (t == 6)
            sprintf(d, "Circlip external %d mm", 10 + 2 * rnd(20));
        else
            sprintf(d, "Oil seal %d x %d x %d", 15 + 5 * rnd(8), 30 + 5 * rnd(10), 7 + rnd(4));
        p->price = 180 + rnd(4500);
        break;
    case CAT_ELEC:
        if (t == 0)
            sprintf(d, "Fuse %dA time-delay", 1 << rnd(6));
        else if (t == 1)
            sprintf(d, "Relay 24 V DC %d-pole", 1 + rnd(4));
        else if (t == 2)
            sprintf(d, "Contactor %d A 3-pole", 9 + 3 * rnd(10));
        else if (t == 3)
            sprintf(d, "Terminal block %d-way", 2 + 2 * rnd(6));
        else if (t == 4)
            sprintf(d, "Cable gland M%d", 12 + 4 * rnd(6));
        else if (t == 5) {
            sprintf(d, "Flex cable %d-core %s mm2", 2 + rnd(4), rnd(2) ? "0.75" : "1.5");
            p->unit = U_METRE;
            p->price = 40 + rnd(400);
        } else if (t == 6)
            sprintf(d, "Proximity sensor M%d PNP", 8 + 4 * rnd(4));
        else if (t == 7)
            sprintf(d, "Push button %s", colours[rnd(5)]);
        else {
            sprintf(d, "Cable tie %d x %d mm", 100 + 50 * rnd(6), 25 + 11 * rnd(3));
            p->unit = U_PACK;
        }
        break;
    case CAT_FLUID:
        if (t == 0)
            sprintf(d, "O-ring %d x %d NBR", 5 + 2 * rnd(30), 1 + rnd(4));
        else if (t == 1)
            sprintf(d, "Push-in fitting %d mm", 4 + 2 * rnd(5));
        else if (t == 2) {
            sprintf(d, "Air hose %d mm PU", 4 + 2 * rnd(5));
            p->unit = U_METRE;
        } else if (t == 3)
            sprintf(d, "Ball valve G%s", threads[rnd(5)]);
        else if (t == 4)
            sprintf(d, "Solenoid valve 5/2 G%s", threads[rnd(4)]);
        else if (t == 5)
            sprintf(d, "Pressure gauge 0-%d bar", 6 + 10 * rnd(25));
        else if (t == 6)
            sprintf(d, "Cylinder %d x %d stroke", 16 + 4 * rnd(10), 25 * (1 + rnd(8)));
        else
            sprintf(d, "Filter regulator G%s", threads[rnd(4)]);
        p->price = 90 + rnd(9000);
        break;
    case CAT_ABRAS:
        if (t < 3)
            sprintf(d, "Flap disc %d mm P%d", PICK(discs), PICK(grits));
        else if (t < 5)
            sprintf(d, "Cutting disc %d x 1.0 mm", PICK(discs));
        else if (t == 5)
            sprintf(d, "Grinding disc %d x 6 mm", PICK(discs));
        else if (t == 6)
            sprintf(d, "Sanding belt %d x %d P%d", 50 + 25 * rnd(4), 450 + 100 * rnd(8),
                    PICK(grits));
        else if (t == 7)
            sprintf(d, "Wire cup brush %d mm", 60 + 10 * rnd(5));
        else {
            sprintf(d, "Abrasive roll %d mm P%d", 25 + 25 * rnd(4), PICK(grits));
            p->unit = U_METRE;
        }
        p->price = 60 + rnd(1500);
        break;
    case CAT_DRIVE:
        if (t < 2)
            sprintf(d, "V-belt SPZ %d", 600 + 25 * rnd(60));
        else if (t == 2)
            sprintf(d, "V-belt A%d", 30 + rnd(40));
        else if (t == 3) {
            sprintf(d, "Roller chain %dB-1", 6 + 2 * rnd(6));
            p->unit = U_METRE;
        } else if (t == 4)
            sprintf(d, "Sprocket %dB %dT", 6 + 2 * rnd(6), 9 + rnd(30));
        else if (t == 5)
            sprintf(d, "Timing belt HTD %d-5M", 300 + 5 * rnd(200));
        else if (t == 6)
            sprintf(d, "Jaw coupling %d mm", 10 + 2 * rnd(15));
        else
            sprintf(d, "Key steel %d x %d x 1 m", 4 + 2 * rnd(5), 4 + 2 * rnd(5));
        p->price = 250 + rnd(6000);
        break;
    case CAT_CHEM:
        p->flags |= rnd(3) ? PF_HAZARD : 0;
        if (t == 0)
            sprintf(d, "Threadlocker medium %d ml", 10 << rnd(3));
        else if (t == 1)
            sprintf(d, "Lithium grease %d g", 400 << rnd(2));
        else if (t == 2) {
            sprintf(d, "Cutting fluid %d l", 1 + 4 * rnd(3));
            p->unit = U_LITRE;
        } else if (t == 3)
            sprintf(d, "Degreaser spray %d ml", 400 + 100 * rnd(2));
        else if (t == 4)
            sprintf(d, "Epoxy two-part %d ml", 25 + 25 * rnd(3));
        else if (t == 5) {
            sprintf(d, "Hydraulic oil HLP %d", 32 + 14 * rnd(3));
            p->unit = U_LITRE;
        } else if (t == 6) {
            sprintf(d, "Anti-seize paste %d g", 100 << rnd(3));
            p->flags &= ~PF_HAZARD;
        } else {
            sprintf(d, "Contact cleaner %d ml", 200 << rnd(2));
        }
        p->price = 300 + rnd(2500);
        break;
    default:
        if (t < 3)
            sprintf(d, "%s drill %d.%d mm", rnd(2) ? "HSS" : "Cobalt", 1 + rnd(12), 5 * rnd(2));
        else if (t == 3)
            sprintf(d, "Machine tap M%d", m);
        else if (t == 4)
            sprintf(d, "End mill %d mm 4-flute", 3 + rnd(14));
        else if (t == 5)
            sprintf(d, "Hole saw %d mm", 16 + 3 * rnd(30));
        else if (t == 6) {
            sprintf(d, "Hacksaw blade %d tpi", 18 + 6 * rnd(3));
            p->unit = U_PACK;
        } else if (t == 7)
            sprintf(d, "Countersink %d mm 90 deg", 6 + 2 * rnd(8));
        else
            sprintf(d, "Reamer H7 %d mm", 3 + rnd(18));
        p->price = 200 + rnd(5000);
        break;
    }
}

/* which characters a text has, a bit each for ' ' to '~': a record can
   only hold the query if it has every character the query has, and holds
   a query of one character if it has that */
static void char_mask(const char *s, unsigned *m)
{
    m[0] = m[1] = m[2] = 0;
    for (; *s; s++) {
        int c = (unsigned char)*s - 32;
        if (c >= 0 && c < 96)
            m[c >> 5] |= 1u << (c & 31);
    }
}

void data_key(Part *p)
{
    char *k = p->key, *e = p->key + sizeof p->key - 1;
    const char *src[5];
    int i;
    src[0] = p->code;
    src[1] = p->desc;
    src[2] = p->supplier;
    src[3] = cat_names[p->cat];
    src[4] = p->bin;
    for (i = 0; i < 5; i++) {
        const char *s = src[i];
        while (*s && k < e) {
            int c = (unsigned char)*s++;
            *k++ = c >= 'A' && c <= 'Z' ? c + 32 : c;
        }
        if (k < e)
            *k++ = '|';         /* nothing the query can contain */
    }
    *k = 0;
    char_mask(p->key, p->mask);
}

void data_generate(unsigned s)
{
    int i, num[NCAT];
    seed = s;
    memset(parts, 0, sizeof parts);
    for (i = 0; i < NCAT; i++)
        num[i] = 1000 + 10 * rnd(40);
    for (i = 0; i < 200; i++) {
        Part *p = &parts[i];
        int c = rnd(NCAT + 2);
        if (c >= NCAT)
            c = CAT_FASTEN;     /* a workshop has more of these */
        p->cat = c;
        p->used = 1;
        num[c] += 1 + rnd(17);
        sprintf(p->code, "%s-%d", cat_code[c], num[c]);
        describe(p);
        strcpy(p->supplier, suppliers[rnd(3) ? c : 8 + rnd(3)]);
        sprintf(p->bin, "%c%02d-%d", 'A' + c, 1 + rnd(24), 1 + rnd(5));
        p->reorder = 5 * (1 + rnd(20));
        p->qty = rnd(5) ? rnd(p->reorder * 4) : rnd(p->reorder);
        if (!rnd(18))
            p->flags |= PF_DISCONT;
        data_key(p);
    }
    nparts = 200;
    nlive = 200;
    last_query[0] = 0;
    for (i = 0; i < nparts; i++)
        order[i] = view[i] = i;
    norder = nview = nparts;
}

int data_new(void)
{
    int i;
    for (i = 0; i < MAXPARTS; i++)
        if (!parts[i].used) {
            memset(&parts[i], 0, sizeof(Part));
            parts[i].used = 1;
            if (i >= nparts)
                nparts = i + 1;
            nlive++;
            order[norder++] = i;
            return i;
        }
    return -1;
}

void data_delete(int i)
{
    int k, n = 0;
    parts[i].used = 0;
    nlive--;
    for (k = 0; k < norder; k++)
        if (order[k] != i)
            order[n++] = order[k];
    norder = n;
    n = 0;
    for (k = 0; k < nview; k++)
        if (view[k] != i)
            view[n++] = view[k];
    nview = n;
}

/* ---- the sort ---- */

static int sort_key, sort_desc;

static int cmp_parts(const void *a, const void *b)
{
    const Part *p = &parts[*(const int *)a], *q = &parts[*(const int *)b];
    int r;
    switch (sort_key) {
    case K_DESC: r = strcmp(p->desc, q->desc); break;
    case K_CAT: r = p->cat - q->cat; break;
    case K_SUPPLIER: r = strcmp(p->supplier, q->supplier); break;
    case K_BIN: r = strcmp(p->bin, q->bin); break;
    case K_QTY: r = p->qty - q->qty; break;
    case K_REORDER: r = p->reorder - q->reorder; break;
    case K_PRICE: r = p->price - q->price; break;
    case K_VALUE: r = p->qty * p->price - q->qty * q->price; break;
    case K_UNIT: r = p->unit - q->unit; break;
    case K_FLAGS: r = p->flags - q->flags; break;
    default: r = 0; break;
    }
    if (!r)
        r = strcmp(p->code, q->code);       /* a total order: the codes are unique */
    return sort_desc ? -r : r;
}

/* The keyed sort: each record's key once, an int (the number, or the
   text's first four characters, which are ASCII, so it stays positive),
   then a merge sort of the indices comparing keys, and the records only
   when their keys are equal. The C library's qsort calls the comparison
   through a pointer for every pair and swaps a byte at a time. */
static int keys[MAXPARTS], tmp[MAXPARTS];

static int key_of(const Part *p, int k)
{
    const unsigned char *s;
    switch (k) {
    case K_CAT: return p->cat;
    case K_QTY: return p->qty;
    case K_REORDER: return p->reorder;
    case K_PRICE: return p->price;
    case K_VALUE: return p->qty * p->price;
    case K_UNIT: return p->unit;
    case K_FLAGS: return p->flags;
    case K_DESC: s = (const unsigned char *)p->desc; break;
    case K_SUPPLIER: s = (const unsigned char *)p->supplier; break;
    case K_BIN: s = (const unsigned char *)p->bin; break;
    default: s = (const unsigned char *)p->code; break;
    }
    if (!s[0])
        return 0;
    if (!s[1])
        return s[0] << 24;
    if (!s[2])
        return s[0] << 24 | s[1] << 16;
    return s[0] << 24 | s[1] << 16 | s[2] << 8 | s[3];
}

/* the keys go the sort's way (negated for a descending sort), so the
   merge compares them inline, and calls cmp_parts only on a tie */
static void merge_sort(int *v, int n)
{
    int width, i, *src = v, *dst = tmp, *t;
    for (width = 1; width < n; width *= 2) {
        for (i = 0; i < n; i += 2 * width) {
            int a = i, am = i + width < n ? i + width : n, b = am;
            int bm = i + 2 * width < n ? i + 2 * width : n, o = i;
            while (a < am && b < bm) {
                int x = src[a], y = src[b], kx = keys[x], ky = keys[y];
                if (kx < ky || (kx == ky && cmp_parts(&x, &y) <= 0)) {
                    dst[o++] = x;
                    a++;
                } else {
                    dst[o++] = y;
                    b++;
                }
            }
            while (a < am)
                dst[o++] = src[a++];
            while (b < bm)
                dst[o++] = src[b++];
        }
        t = src;
        src = dst;
        dst = t;
    }
    if (src != v)
        memcpy(v, src, n * sizeof(int));
}

void data_sort(int k, int desc)
{
    char q[40];
    int i;
    sort_key = k;
    sort_desc = desc;
    if (sort_mode) {
        for (i = 0; i < norder; i++) {
            int key = key_of(&parts[order[i]], k);
            keys[order[i]] = desc ? -key : key;
        }
        merge_sort(order, norder);
    } else {
        qsort(order, norder, sizeof(int), cmp_parts);
    }
    /* the view again, in the new order */
    strcpy(q, last_query);
    last_query[0] = 1;          /* not a prefix of anything: a full filter */
    data_filter(q);
}

/* ---- the filter ---- */

#ifdef GFX_ASM
/* filter.s: whether key contains q (lower case, at least a character) */
int key_has(const char *key, const char *q, int qlen);
#endif

/* whether the key holds the query: the first character found by a scan,
   then the rest compared */
static int key_has_c(const char *key, const char *q, int qlen)
{
    int c0 = (unsigned char)q[0], k;
    const unsigned char *s = (const unsigned char *)key;
    for (; *s; s++) {
        if (*s != c0)
            continue;
        for (k = 1; k < qlen; k++)
            if (s[k] != (unsigned char)q[k])
                break;
        if (k == qlen)
            return 1;
    }
    return 0;
}

void data_filter(const char *query)
{
    char q[40];
    int qlen = 0, i, n = 0, narrow;
    const int *from;
    int nfrom;
    int (*has)(const char *, const char *, int) = key_has_c;
    unsigned qm[3];
    while (query[qlen] && qlen < 39) {
        int c = (unsigned char)query[qlen];
        q[qlen++] = c >= 'A' && c <= 'Z' ? c + 32 : c;
    }
    q[qlen] = 0;
#ifdef GFX_ASM
    if (filter_mode == 2)
        has = key_has;
#endif
    /* typing a character only narrows the view: search just the view */
    narrow = filter_mode && last_query[0] != 1 && strncmp(q, last_query, strlen(last_query)) == 0;
    from = narrow ? view : order;
    nfrom = narrow ? nview : norder;
    filter_scanned = qlen ? nfrom : 0;
    if (!qlen) {
        for (i = 0; i < norder; i++)
            view[i] = order[i];
        n = norder;
    } else if (filter_mode == 3) {
        /* the characters first: most records fail on them, and the rest
           are scanned */
        char_mask(q, qm);
        filter_scanned = 0;
        for (i = 0; i < nfrom; i++) {
            const Part *p = &parts[from[i]];
            if ((qm[0] & ~p->mask[0]) | (qm[1] & ~p->mask[1]) | (qm[2] & ~p->mask[2]))
                continue;
            filter_scanned++;
            if (qlen == 1 || has(p->key, q, qlen))
                view[n++] = from[i];
        }
    } else {
        for (i = 0; i < nfrom; i++)
            if (has(parts[from[i]].key, q, qlen))
                view[n++] = from[i];     /* from is view or order: n <= i, so in place is fine */
    }
    nview = n;
    strcpy(last_query, q);
}

int data_find(int i)
{
    int k;
    for (k = 0; k < nview; k++)
        if (view[k] == i)
            return k;
    return -1;
}
