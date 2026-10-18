/* The forms application's backend: a workshop's parts store, about 200
   records made up by a deterministic generator, kept in memory; the
   view the list shows (the records that match the search, in the sort
   order), and the measurements of the filter and the sort. */

#ifndef DATA_H
#define DATA_H

#define MAXPARTS 256

enum { CAT_FASTEN, CAT_BEARING, CAT_ELEC, CAT_FLUID, CAT_ABRAS, CAT_DRIVE, CAT_CHEM, CAT_TOOL,
       NCAT };
enum { U_EACH, U_PACK, U_METRE, U_KG, U_LITRE, NUNIT };

#define PF_HAZARD   1           /* hazardous: stored apart */
#define PF_DISCONT  2           /* discontinued: not reordered */

typedef struct {
    char code[10];              /* FA-1042 */
    char desc[36];
    char supplier[22];
    char bin[8];                /* A07-3 */
    unsigned char cat, unit, flags, used;
    int qty, reorder;
    int price;                  /* cents */
    char key[88];               /* what the search looks in, lower case */
    unsigned mask[3];           /* the characters it has (filter_mode 3) */
    /* to 256 bytes: parts[i]'s address is then a shift; at 192 the
       compiler multiplies, a microcoded loop of tens of cycles */
    char pad[64];
} Part;

extern Part parts[MAXPARTS];
extern int nparts;              /* slots used, deleted ones included */
extern const char *cat_names[NCAT];
extern const char *unit_names[NUNIT];
extern const char *suppliers[];
extern int nsuppliers;

/* the view: indices into parts, matching the query, in the sort order */
extern int view[MAXPARTS];
extern int nview, nlive;

/* the columns a sort can use */
enum { K_CODE, K_DESC, K_CAT, K_SUPPLIER, K_BIN, K_QTY, K_REORDER, K_PRICE, K_VALUE, K_UNIT,
       K_FLAGS };

void data_generate(unsigned seed);
void data_key(Part *p);                     /* rebuild the search text after a change */
int data_new(void);                         /* a free slot, cleared; -1 if full */
void data_delete(int i);

/* the sort: the order of every live record, by column k */
void data_sort(int k, int desc);
/* the filter: the view from the sorted order; the query is lower-cased
   here. Incremental when the query extends the last one (a character
   typed): only the current view is searched. */
void data_filter(const char *query);
/* filter_mode: 0 the whole order each time, 1 incremental where it can,
   2 incremental with the search's inner loop in assembly (asm builds),
   3 incremental, the records without the query's characters skipped
   before the scan */
extern int filter_mode;
extern int sort_mode;           /* 0 the C library's qsort, 1 a keyed merge sort */
extern unsigned filter_scanned;             /* records looked at by the last filter */
/* where record i is in the view, or -1 */
int data_find(int i);

#endif
