/* Fighting: the nearest enemy, found through spatial buckets; chasing it
   and striking it, or shooting arrows at it; and the fallen.

   The buckets are squares of BCELL pixels, a list of units each, one set
   of lists a team, made again every tick (a unit moves less than a
   bucket in a tick, but moving units between lists would cost about
   as much). A search looks at the buckets in rings round the unit's own,
   nearest first, and stops when the next ring can't hold anything
   nearer than what it has found. */

#include <string.h>
#include "rts.h"

#define BSHIFT 10               /* a bucket is 64 pixels: a position >> BSHIFT */
#define BCELL (1 << BSHIFT)     /* in position units */
#define B_W ((MAP_W * TILE * 16 + BCELL - 1) >> BSHIFT)
#define B_H ((MAP_H * TILE * 16 + BCELL - 1) >> BSHIFT)

static short bhead[2][B_W * B_H];       /* each bucket's first unit, or -1 */
static short bnext[MAX_UNITS];          /* the next in its bucket */
int blows, arrows, kills[2];

void buckets_build(void)
{
    int k, b;
    Unit *u = units;
    memset(bhead, 0xFF, sizeof bhead);
    for (k = 0; k < nunits; k++, u++) {
        if (u->state == S_DEAD)
            continue;
        b = (u->y >> BSHIFT) * B_W + (u->x >> BSHIFT);
        bnext[k] = bhead[u->team][b];
        bhead[u->team][b] = k;
    }
}

/* The nearest unit in one bucket's list to (ux, uy), if nearer than
   *bd, by vlen's measure: its index, or best */
static int nearest_in(int k, int ux, int uy, int *bd, int best)
{
    int ax, ay, d, b = *bd;
    for (; k >= 0; k = bnext[k]) {
        ax = units[k].x - ux;
        if (ax < 0)
            ax = -ax;
        if (ax >= b)
            continue;           /* no nearer, on one axis alone */
        ay = units[k].y - uy;
        if (ay < 0)
            ay = -ay;
        if (ay >= b)
            continue;
        d = ax > ay ? ax + ((ay + ay + ay) >> 3) : ay + ((ax + ax + ax) >> 3);
        if (d < b) {
            b = d;
            best = k;
        }
    }
    *bd = b;
    return best;
}

/* The nearest unit of the other team within range (position units), by
   vlen's measure, or -1. Ties go to the first found, which is the same
   on any machine. */
int nearest_enemy(const Unit *u, int range)
{
    const short *heads = bhead[!u->team], *row;
    int ux = u->x, uy = u->y, bx = ux >> BSHIFT, by = uy >> BSHIFT, best = -1, bd = range + 1;
    int r, x, y, rmax = (range >> BSHIFT) + 1, step;
    for (r = 0; r <= rmax; r++) {
        /* anything in ring r is at least r - 1 buckets away */
        if (best >= 0 && bd <= (r - 1) * BCELL)
            break;
        for (y = by - r; y <= by + r; y++) {
            if (y < 0 || y >= B_H)
                continue;
            row = heads + y * B_W;
            /* the ring's top and bottom rows whole, its sides' two buckets */
            step = y == by - r || y == by + r ? 1 : 2 * r;
            for (x = bx - r; x <= bx + r; x += step)
                if (x >= 0 && x < B_W && row[x] >= 0)
                    best = nearest_in(row[x], ux, uy, &bd, best);
        }
    }
    return best;
}

/* ---- arrows ---- */

#define MAX_ARROWS 128
#define ARROW_SPEED (24 << 4)   /* a tick */

typedef struct {
    int x, y;
    short target, ticks;
    unsigned char damage, team, pad[2];
} Arrow;

static Arrow flying[MAX_ARROWS];
static int narrows;             /* slots used, from 0 */

static void hit(Unit *t, int damage, int from)
{
    if (t->hp <= damage) {
        t->hp = 0;              /* it falls at the end of the tick (deaths) */
        return;
    }
    t->hp -= damage;
    /* struck while standing or marching: it turns to fight */
    if (t->type != U_WORKER && (t->state == S_IDLE || t->state == S_AMOVE) && from >= 0) {
        t->after = t->state;
        t->state = S_FIGHT;
        t->target = from;
    }
}

static void shoot(Unit *u, Unit *t)
{
    Arrow *a;
    int i;
    for (i = 0; i < narrows && flying[i].ticks > 0; i++)
        ;
    if (i == MAX_ARROWS)
        return;                 /* the sky is full */
    if (i == narrows)
        narrows++;
    a = &flying[i];
    a->x = u->x;
    a->y = u->y - (8 << 4);     /* from the bow, about shoulder height */
    a->target = t - units;
    a->ticks = vlen(t->x - u->x, t->y - u->y) / ARROW_SPEED + 1;
    a->damage = utypes[u->type].damage;
    a->team = u->team;
    arrows++;
}

/* each arrow a tick nearer its target; it hits when it gets there */
void arrows_fly(void)
{
    int i;
    Arrow *a = flying;
    for (i = 0; i < narrows; i++, a++) {
        Unit *t;
        if (a->ticks <= 0)
            continue;
        t = &units[a->target];
        a->x += (t->x - a->x) / a->ticks;
        a->y += (t->y - (8 << 4) - a->y) / a->ticks;
        if (--a->ticks == 0 && t->state != S_DEAD && t->hp > 0)
            hit(t, a->damage, -1);
    }
    while (narrows > 0 && flying[narrows - 1].ticks <= 0)
        narrows--;
}

/* ---- a fighting unit's tick ---- */

void combat(Unit *u, int k)
{
    const UnitType *ty = &utypes[u->type];
    Unit *t = &units[u->target];
    int d;
    if (t->state == S_DEAD || t->hp == 0) {
        /* its enemy has fallen: the next, or back to what it was doing */
        int n = nearest_enemy(u, ty->sight);
        if (n < 0) {
            u->state = u->after;
            u->after = S_IDLE;
            u->target = -1;
            u->vx = u->vy = 0;
            u->wait = 0;
            return;
        }
        u->target = n;
        t = &units[n];
    }
    d = vlen(t->x - u->x, t->y - u->y);
    if (d > ty->sight + (ty->sight >> 1)) {
        u->state = u->after;    /* it got away */
        u->after = S_IDLE;
        u->target = -1;
        u->wait = 0;
        return;
    }
    u->anim = (u->anim & ~1) | (t->x < u->x);
    if (d > ty->range) {
        /* chase: straight at it, round whoever is in the way */
        unit_head_for(u, t->x, t->y);
        return;
    }
    u->vx = u->vy = 0;
    if (u->cool)
        return;
    u->cool = ty->cooldown;
    blows++;
    if (u->type == U_ARCHER)
        shoot(u, t);
    else
        hit(t, ty->damage, k);
}

/* ---- the fallen ---- */

/* the units struck down this tick: off the grid, out of their fields, a
   mark on the ground where they fell */
void deaths(void)
{
    int k, c;
    Unit *u = units;
    for (k = 0; k < nunits; k++, u++) {
        if (u->hp > 0 || u->state == S_DEAD)
            continue;
        u->state = S_DEAD;
        u->vx = u->vy = 0;
        unit_release(u);
        occ[(u->y >> OSHIFT) * OCC_W + (u->x >> OSHIFT)] = 0;
        c = CELL(u->x >> TSHIFT, u->y >> TSHIFT);
        if (decal[c] < 255)
            decal[c]++;
        minimap_fallen(c);
        tile_dirty(u->x >> TSHIFT, u->y >> TSHIFT);
        alive[u->team]--;
        kills[!u->team]++;
    }
}
