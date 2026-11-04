/* The units: soldiers, archers, and workers walking between their hall
   and the forest; their orders, formations, walking and steering.
   Follows studies/mini_gfx/games/rts/units.c on Heron Mini's branch,
   which has the walking and the formations; the occupancy grid, the
   steering round other units and the fighting (combat.c) are new.

   A unit walks from cell centre to cell centre down a flow field
   (map.c), and straight to its own place in the formation at the end; it
   plans its next step only when it reaches a waypoint, so most ticks a
   walking unit costs a step on the occupancy grid. A step into a cell
   another unit holds is tried again 45 and then 90 degrees to either
   side; a unit that can't step for a while plans again. */

#include <string.h>
#include "rts.h"

Unit units[MAX_UNITS];
int nunits, alive[2];
unsigned short occ[OCC_W * OCC_H];
int steps_blocked, side_steps;

/* hp, speed, range, damage, cooldown, sight; a tick is a fifth of a
   second, so a soldier walks 60 pixels a second */
const UnitType utypes[U_NTYPES] = {
    { 30, 10 << 4, 14 << 4, 3, 3, 64 << 4 },   /* worker */
    { 50, 12 << 4, 15 << 4, 10, 2, 112 << 4 }, /* soldier */
    { 35, 11 << 4, 88 << 4, 7, 3, 120 << 4 },  /* archer */
};

/* the formation: offsets in a spiral, 14 pixels apart */
#define NSLOT 64
#define SLOT_GAP 14
static signed char spiral[NSLOT][2];

int iabs(int v) { return v < 0 ? -v : v; }

int vlen(int dx, int dy)
{
    int a = iabs(dx), b = iabs(dy);
    return a > b ? a + ((b + b + b) >> 3) : b + ((a + a + a) >> 3);
}

static void spiral_make(void)
{
    int n = 0, r, x, y;
    spiral[n][0] = spiral[n][1] = 0;
    n++;
    for (r = 1; n < NSLOT; r++)
        for (y = -r; y <= r && n < NSLOT; y++)
            for (x = -r; x <= r && n < NSLOT; x++)
                if (iabs(x) == r || iabs(y) == r) {
                    spiral[n][0] = x;
                    spiral[n][1] = y;
                    n++;
                }
}

static int occ_cell(int x, int y)
{
    return (y >> OSHIFT) * OCC_W + (x >> OSHIFT);
}

/* (the units and the occupancy grid are static, so they start empty) */
void units_init(void)
{
    spiral_make();
    nunits = 0;
    alive[0] = alive[1] = 0;
}

/* ---- walking ---- */

/* head for (wx, wy), world pixels x 16, in a straight line: the last
   step lands on it */
void unit_head_for(Unit *u, int wx, int wy)
{
    int dx = wx - u->x, dy = wy - u->y, len = vlen(dx, dy), s = utypes[u->type].speed;
    if (len <= s) {
        u->vx = dx;
        u->vy = dy;
        u->wait = 1;
    } else {
        u->vx = dx * s / len;
        u->vy = dy * s / len;
        u->wait = len / s;
    }
    if (u->vx)
        u->anim = (u->anim & ~1) | (u->vx < 0);
}

void unit_release(Unit *u)
{
    if (u->field >= 0 && fields[u->field].users > 0)
        fields[u->field].users--;
    u->field = -1;
}

static void follow(Unit *u, int f)
{
    unit_release(u);
    u->field = f;
    if (f >= 0)
        fields[f].users++;
    u->wait = 0;
    u->blocked = 0;
}

/* The next waypoint: down the field to the cell nearest the target, or
   straight on near its goal (gx, gy); 0 when it has arrived. */
static int plan(Unit *u)
{
    int tx = u->x >> TSHIFT, ty = u->y >> TSHIFT, c = CELL(tx, ty);
    unsigned short *d;
    int best, bx = 0, by = 0, dx, dy, nx, ny, far;
    if (iabs(u->gx - u->x) < 16 && iabs(u->gy - u->y) < 16)
        return 0;
    /* blocked a while near its place: someone has it, so this will do */
    if (u->blocked > 4 && vlen(u->gx - u->x, u->gy - u->y) < (2 * TILE) << 4)
        return 0;
    if (u->field < 0) {
        /* a straight walk; it stops at anything two steps ahead */
        unit_head_for(u, u->gx, u->gy);
        if (u->wait > 8)
            u->wait = 8;
        return walkable((u->x + 2 * u->vx) >> TSHIFT, (u->y + 2 * u->vy) >> TSHIFT);
    }
    d = fields[u->field].dist;
    far = d[c] == FIELD_FAR;
    if (far && fields[u->field].done)
        return 0;               /* no way there */
    if (far || vlen(u->gx - u->x, u->gy - u->y) < (2 * TILE) << 4) {
        /* the search hasn't come this far, or nearly there: straight on,
           unless the cell two steps that way is blocked */
        unit_head_for(u, u->gx, u->gy);
        nx = (u->x + 2 * u->vx) >> TSHIFT;
        ny = (u->y + 2 * u->vy) >> TSHIFT;
        if (!walkable(nx, ny) && !far)
            goto down;
        if (!walkable(nx, ny)) {
            u->wait = 4;        /* wait for the search */
            u->vx = u->vy = 0;
        } else if (u->wait > 6) {
            u->wait = 6;        /* look again soon: the search may arrive */
        }
        return 1;
    }
down:
    best = d[c];
    for (dy = -1; dy <= 1; dy++)
        for (dx = -1; dx <= 1; dx++) {
            int n = c + dy * MAP_W + dx;
            if ((dx || dy) && d[n] < best && pass[n] &&
                (!dx || !dy || (pass[c + dx] && pass[c + dy * MAP_W]))) {
                best = d[n];
                bx = dx;
                by = dy;
            }
        }
    if (best == d[c])
        return 0;               /* at the target's cell, its place unreachable */
    unit_head_for(u, ((tx + bx) * TILE + TILE / 2) << 4, ((ty + by) * TILE + TILE / 2) << 4);
    return 1;
}

static int is_tree(int t) { return t == T_TREE || t == T_TREE2; }

/* a walkable cell next to the forest near the hall, for the workers: the
   nearest, ring by ring, but not by the wall of trees round the map */
static void find_wood(int *wx, int *wy)
{
    int r, x, y, c, step, bx = base_x[0], by = base_y[0];
    for (r = 3; r < 12; r++)
        for (y = by - r; y <= by + r; y++) {
            if (y < 2 || y >= MAP_H - 2)
                continue;
            step = y == by - r || y == by + r ? 1 : 2 * r;
            for (x = bx - r; x <= bx + r; x += step) {
                c = CELL(x, y);
                if (x >= 2 && x < MAP_W - 2 && pass[c] &&
                    (is_tree(map[c + 1]) || is_tree(map[c - 1]) || is_tree(map[c + MAP_W]) ||
                     is_tree(map[c - MAP_W]))) {
                    *wx = x;
                    *wy = y;
                    return;
                }
            }
        }
    *wx = bx + 3;
    *wy = by + 3;
}

/* ---- steering ---- */

/* a step to (nx, ny) if its tile is walkable and its occupancy cell is
   free or the unit's own */
static int try_step(Unit *u, int k, int nx, int ny)
{
    int from = occ_cell(u->x, u->y), to = occ_cell(nx, ny);
    if (nx < 0 || ny < 0 || !pass[CELL(nx >> TSHIFT, ny >> TSHIFT)])
        return 0;
    if (to != from) {
        if (occ[to])
            return 0;
        occ[from] = 0;
        occ[to] = k + 1;
    }
    u->x = nx;
    u->y = ny;
    return 1;
}

void unit_steer(Unit *u, int k)
{
    int vx = u->vx, vy = u->vy, rx, ry, side;
    if (!vx && !vy)
        return;
    if (try_step(u, k, u->x + vx, u->y + vy)) {
        u->blocked = 0;
        u->anim ^= 2;
        return;
    }
    /* 45 degrees to one side, then the other (alternating between units,
       so a crowd parts), then 90 */
    rx = ((vx - vy) * 181) >> 8;
    ry = ((vx + vy) * 181) >> 8;
    side = (k & 1) ? 1 : -1;
    if (try_step(u, k, u->x + (side > 0 ? rx : ry), u->y + (side > 0 ? ry : -rx)) ||
        try_step(u, k, u->x + (side > 0 ? ry : rx), u->y + (side > 0 ? -rx : ry)) ||
        try_step(u, k, u->x - side * vy, u->y + side * vx) ||
        try_step(u, k, u->x + side * vy, u->y - side * vx)) {
        side_steps++;
        u->anim ^= 2;
        u->wait++;              /* it's off its line: a tick longer to the waypoint */
        return;
    }
    steps_blocked++;
    if (u->blocked < 255)
        u->blocked++;
    if (u->blocked > 3)
        u->wait = 0;            /* plan again from here */
}

/* ---- orders ---- */

/* a unit of a type at the nearest free walkable cell round (cx, cy);
   -1 if there is none near. Units are mostly added in groups round the
   same place, so the search starts at the ring where the last one was
   put. */
int unit_add(int type, int team, int group, int cx, int cy)
{
    static int last_x = -1, last_y = -1, last_r;
    int r, dx, dy, x, y, k = nunits;
    Unit *u = &units[k];
    if (k >= MAX_UNITS)
        return -1;
    if (cx != last_x || cy != last_y)
        last_r = 0;
    last_x = cx;
    last_y = cy;
    for (r = last_r; r < 12; r++)
        for (dy = -r; dy <= r; dy++)
            for (dx = -r; dx <= r; dx++) {
                if (iabs(dx) != r && iabs(dy) != r)
                    continue;
                /* a quarter of the tile, the next for the next unit */
                x = ((cx + dx) * TILE + 4 + 8 * (k & 1)) << 4;
                y = ((cy + dy) * TILE + 4 + 8 * ((k >> 1) & 1)) << 4;
                if (walkable(cx + dx, cy + dy) && !occ[occ_cell(x, y)]) {
                    memset(u, 0, sizeof *u);
                    u->x = x + rnd_n(4 << 4);
                    u->y = y + rnd_n(4 << 4);
                    u->gx = u->x;
                    u->gy = u->y;
                    u->type = type;
                    u->team = team;
                    u->group = group;
                    u->hp = utypes[type].hp;
                    u->field = -1;
                    u->target = -1;
                    u->state = type == U_WORKER ? S_TO_WOOD : S_IDLE;
                    u->after = S_IDLE;
                    u->wait = type == U_WORKER ? k % 9 : 0;     /* not all at once */
                    occ[occ_cell(u->x, u->y)] = k + 1;
                    alive[team]++;
                    last_r = r;
                    return nunits++;
                }
            }
    return -1;
}

/* the group's walk to cell (tx, ty): a flow field from there, and each
   unit its own place round it, the next spiral slot that's walkable */
void units_order(int team, int group, int tx, int ty, int amove)
{
    int f = field_new(tx, ty), k, s = 0;
    if (f < 0)
        return;
    for (k = 0; k < nunits; k++) {
        Unit *u = &units[k];
        int gx, gy;
        if (u->team != team || u->group != group || u->state == S_DEAD)
            continue;
        for (; s < NSLOT; s++) {
            gx = fields[f].tx * TILE + TILE / 2 + spiral[s][0] * SLOT_GAP;
            gy = fields[f].ty * TILE + TILE / 2 + spiral[s][1] * SLOT_GAP;
            if (walkable(gx / TILE, gy / TILE))
                break;
        }
        if (s == NSLOT)
            s = 0;
        u->gx = (fields[f].tx * TILE + TILE / 2 + spiral[s][0] * SLOT_GAP) << 4;
        u->gy = (fields[f].ty * TILE + TILE / 2 + spiral[s][1] * SLOT_GAP) << 4;
        s++;
        u->state = amove ? S_AMOVE : S_MOVE;
        u->after = S_IDLE;
        u->target = -1;
        follow(u, f);
    }
}

/* ---- each tick ---- */

/* the workers' two fields, made the first time they're needed */
static int f_wood = -1, f_hall = -1, wood_x, wood_y;

/* a worker with nowhere to walk: the next step of its round */
static void next_job(Unit *u)
{
    switch (u->state) {
    case S_TO_WOOD:
        if (f_wood < 0) {
            find_wood(&wood_x, &wood_y);
            f_wood = field_new(wood_x, wood_y);
        }
        u->gx = (wood_x * TILE + 4 + rnd_n(8)) << 4;
        u->gy = (wood_y * TILE + 4 + rnd_n(8)) << 4;
        follow(u, f_wood);
        u->after = S_CHOP;
        u->state = S_MOVE;
        break;
    case S_CHOP:
        u->wait = 12 + rnd_n(8);
        u->state = S_TO_HALL;
        break;
    case S_TO_HALL:
        if (f_hall < 0)
            f_hall = field_new(base_x[0], base_y[0] + 2);
        u->gx = ((base_x[0] - 1) * TILE + rnd_n(3 * TILE)) << 4;
        u->gy = ((base_y[0] + 2) * TILE + 4 + rnd_n(8)) << 4;
        follow(u, f_hall);
        u->after = S_UNLOAD;
        u->state = S_MOVE;
        break;
    case S_UNLOAD:
        u->wait = 4;
        u->state = S_TO_WOOD;
        break;
    }
}

/* a walking unit's tick: plan when its waypoint is reached; at its goal,
   the state its walk ends in */
static void walk(Unit *u)
{
    if (--u->wait > 0)
        return;
    if (!plan(u)) {
        u->vx = u->vy = 0;
        u->wait = 0;
        unit_release(u);
        u->state = u->after;
        u->after = S_IDLE;
    }
}

void units_think(int tick)
{
    int k, t;
    Unit *u = units;
    for (k = 0; k < nunits; k++, u++) {
        if (u->state == S_DEAD)
            continue;
        if (u->cool)
            u->cool--;
        /* look round every eighth tick, each unit in its turn */
        if (((k + tick) & 7) == 0 && u->type != U_WORKER &&
            (u->state == S_IDLE || u->state == S_AMOVE)) {
            t = nearest_enemy(u, utypes[u->type].sight);
            if (t >= 0) {
                u->after = u->state;    /* afterwards, go on as before */
                u->state = S_FIGHT;
                u->target = t;
            }
        }
        switch (u->state) {
        case S_FIGHT:
            combat(u, k);
            break;
        case S_MOVE:
        case S_AMOVE:
            walk(u);
            break;
        case S_IDLE:
            u->vx = u->vy = 0;
            break;
        default:                /* a worker between walks */
            u->vx = u->vy = 0;
            if (--u->wait <= 0)
                next_job(u);
            break;
        }
        unit_steer(u, k);
    }
}
