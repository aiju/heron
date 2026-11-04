/* A real-time strategy game's logic, headless (rts.h has the plan): the
   set-up, the scripted orders both sides are given, and the tick.

   The map is made from a seed; each side's army stands on its own bank
   of the river near the first ford, a second group near the second, and
   the player's workers walk between their hall and the forest. Then the
   script plays: the enemy crosses at the first ford and sends a second
   wave over the second, the player holds and then pushes back. Each
   tick: the script's orders, the flow fields' searches, the buckets,
   every unit's tick, the arrows, the fallen, and the frame's
   bookkeeping. Every REPORT ticks the units' state is hashed into the
   results, and every minimap as it's made. */

#include "bench.h"
#include "rts.h"

#define SEED 7
#define FIELD_BUDGET (MAP_N / 24)       /* cells searched a tick, all fields together */

unsigned rng_state = 1;

unsigned rnd(void)
{
    rng_state = rng_state * 1103515245u + 12345u;
    return rng_state >> 16;
}

/* scaled rather than divided: a multiply is cheaper than a remainder */
int rnd_n(int n) { return (int)(((rnd() & 0x7FFF) * (unsigned)n) >> 15); }

/* ---- the armies ---- */

/* where things are, named so the script can work on any map */
enum { AT_FORD0, AT_FORD1, AT_HALL0, AT_HALL1 };

static void place_of(int at, int dx, int dy, int *x, int *y)
{
    switch (at) {
    case AT_FORD0: *x = ford_x[0]; *y = ford_y[0]; break;
    case AT_FORD1: *x = ford_x[1]; *y = ford_y[1]; break;
    case AT_HALL0: *x = base_x[0]; *y = base_y[0] + 3; break;
    default: *x = base_x[1]; *y = base_y[1] - 3; break;
    }
    *x += dx;
    *y += dy;
    if (*x < 1)
        *x = 1;
    if (*x > MAP_W - 2)
        *x = MAP_W - 2;
    if (*y < 1)
        *y = 1;
    if (*y > MAP_H - 2)
        *y = MAP_H - 2;
}

/* a group of n units of a type, round a place */
static void muster(int type, int team, int group, int n, int at, int dx, int dy)
{
    int x, y;
    place_of(at, dx, dy, &x, &y);
    while (n-- > 0)
        unit_add(type, team, group, x, y);
}

static void armies(void)
{
    int half = NUNITS / 2, workers = NUNITS / 12, n0 = half - workers;
    /* the player's: workers by the hall, two groups at the first ford, one at the second */
    muster(U_WORKER, 0, 3, workers, AT_HALL0, 0, 0);
    muster(U_SOLDIER, 0, 0, n0 * 2 / 5, AT_FORD0, -2, 0);
    muster(U_ARCHER, 0, 1, n0 * 3 / 10, AT_FORD0, -6, 0);
    muster(U_SOLDIER, 0, 2, n0 - n0 * 2 / 5 - n0 * 3 / 10, AT_FORD1, -4, 0);
    /* the enemy's, across the river */
    muster(U_SOLDIER, 1, 0, half * 2 / 5, AT_FORD0, 3, 0);
    muster(U_ARCHER, 1, 1, half / 4, AT_FORD0, 7, 0);
    muster(U_SOLDIER, 1, 2, half - half * 2 / 5 - half / 4, AT_FORD1, 5, 0);
}

/* ---- the script ----
   The benchmark's sizes play its first few ticks; the rest is there for
   longer runs (a bigger TICKS). */

typedef struct {
    short tick;
    unsigned char team, group, amove;
    unsigned char at;
    signed char dx, dy;
} Order;

static const Order script[] = {
    { 0, 1, 0, 1, AT_FORD0, -3, 0 },    /* their soldiers over the first ford */
    { 0, 1, 1, 1, AT_FORD0, 4, 1 },     /* their archers to its bank */
    { 0, 0, 0, 1, AT_FORD0, -2, 0 },    /* ours to meet them at our end of it */
    { 1, 0, 1, 0, AT_FORD0, -5, -1 },   /* our archers behind */
    { 2, 1, 2, 1, AT_FORD1, -3, 0 },    /* their second wave over the second ford */
    { 3, 0, 2, 1, AT_FORD1, -1, 0 },    /* ours to hold it */
    { 8, 1, 2, 1, AT_HALL0, 2, 2 },     /* their second wave on to our hall */
    { 10, 0, 0, 1, AT_FORD0, 4, 0 },    /* ours push over the first ford */
    { 12, 0, 1, 1, AT_FORD0, 1, 0 },    /* our archers into the ford */
    { 14, 1, 0, 1, AT_FORD0, 5, 2 },    /* theirs fall back */
    { 16, 0, 2, 1, AT_HALL0, 0, 3 },    /* ours back to the hall */
    { 20, 0, 0, 1, AT_HALL1, 0, 0 },    /* and on to theirs */
    { 20, 0, 1, 1, AT_FORD0, 6, 0 },
};
#define NSCRIPT (sizeof script / sizeof script[0])

static void orders(int tick)
{
    int k, x, y;
    for (k = 0; k < NSCRIPT; k++)
        if (script[k].tick == tick) {
            place_of(script[k].at, script[k].dx, script[k].dy, &x, &y);
            units_order(script[k].team, script[k].group, x, y, script[k].amove);
        }
}

/* ---- the results ---- */

static unsigned hash_word(unsigned h, unsigned w)
{
    return ((h << 5) + h) ^ w;
}

static unsigned units_hash(unsigned h)
{
    int k;
    const Unit *u = units;
    for (k = 0; k < nunits; k++, u++) {
        h = hash_word(h, u->x);
        h = hash_word(h, u->y ^ u->hp << 16 ^ u->state << 24);
    }
    return h;
}

int main(void)
{
    int tick;
    unsigned uh = BENCH_HASH0;
    map_make(SEED);
    units_init();
    armies();
    view_init();
    minimap_init();
    bench_report("units", nunits);
    for (tick = 0; tick < TICKS; tick++) {
        orders(tick);
        field_step(FIELD_BUDGET);
        buckets_build();
        units_think(tick);
        arrows_fly();
        deaths();
        view_frame(tick);
        if ((tick + 1) % REPORT == 0)
            uh = units_hash(uh);
    }
    bench_report("state", uh);
    bench_report("minimap", minimap_hash());
    bench_report("frames", frame_sum);
    bench_report("alive", alive[0] << 16 | alive[1]);
    bench_report("kills", kills[0] << 16 | kills[1]);
    bench_report("blows", blows << 16 | arrows);
    bench_report("fields", fields_made << 24 | field_cells);
    bench_report("steps", steps_blocked << 16 | side_steps);
    bench_report("drawn", dirty_tiles << 16 | items_drawn);
    return 0;
}
