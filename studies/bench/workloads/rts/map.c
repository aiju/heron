/* The map: made from a seed (grass, lakes, a river with two fords,
   forests, rocks, two halls), and searched for paths with flow fields.
   Follows studies/mini_gfx/games/rts/map.c on Heron Mini's branch,
   without the world bitmaps it draws the map into; the fields' arrays
   are static here, as the machine has no allocator worth the name. */

#include <string.h>
#include "rts.h"

unsigned char map[MAP_N], pass[MAP_N], decal[MAP_N];
int base_x[2], base_y[2], ford_x[2], ford_y[2], river_x;
Field fields[NFIELD];
int fields_made, field_cells;

static unsigned short field_dist[NFIELD][MAP_N], field_queue[NFIELD][MAP_N];

static int is_water(int t) { return t >= T_WATER && t < T_WATER + 16; }

static int blocks(int t)
{
    return t == T_TREE || t == T_TREE2 || t == T_ROCK || t == T_ROCK2 || is_water(t) ||
           t >= T_BASE;
}

static unsigned char blocking[T_N];     /* blocks(t), for every tile */

/* the grass's tiles, by four random bits */
static const unsigned char grass[16] = {
    T_GRASS, T_GRASS, T_GRASS, T_GRASS, T_GRASS, T_GRASS, T_GRASS, T_GRASS,
    T_GRASS2, T_GRASS2, T_GRASS2, T_GRASS3, T_GRASS3, T_GRASS3, T_GRASS4, T_FLOWER
};

int walkable(int tx, int ty)
{
    if (tx < 0 || ty < 0 || tx >= MAP_W || ty >= MAP_H)
        return 0;
    return pass[CELL(tx, ty)];
}

static void put(int x, int y, int t)
{
    if (x > 0 && y > 0 && x < MAP_W - 1 && y < MAP_H - 1)
        map[CELL(x, y)] = t;
}

/* a blob of tile t: n random steps from (x, y), each painting a cross */
static void blob(int x, int y, int n, int t)
{
    while (n-- > 0) {
        put(x, y, t);
        put(x + 1, y, t);
        put(x, y + 1, t);
        if (t == T_WATER) {
            put(x - 1, y, t);
            put(x, y - 1, t);
        }
        x += rnd_n(3) - 1;
        y += rnd_n(3) - 1;
    }
}

/* keep a 3 x 3 clearing round (x, y): a ford's banks */
static void clear_round(int x, int y)
{
    int dx, dy, t;
    for (dy = -1; dy <= 1; dy++)
        for (dx = -1; dx <= 1; dx++) {
            t = map[CELL(x + dx, y + dy)];
            if (blocking[t] && !is_water(t))
                put(x + dx, y + dy, T_GRASS);
        }
}

void map_make(unsigned seed)
{
    int x, y, k, n = MAP_N, f = 0;
    unsigned bits = 0;
    rng_state = seed;
    for (k = 0; k < T_N; k++)
        blocking[k] = blocks(k);
    /* grass, a little varied, flowers here and there: four cells from
       each random number */
    for (k = 0; k < n; k++) {
        if ((k & 3) == 0)
            bits = rnd();
        map[k] = grass[bits & 15];
        bits >>= 4;
    }
    /* lakes, forests, rocks (the random numbers drawn one statement at
       a time: C leaves the order of a call's arguments open, and gcc and
       Heron's compiler take them in different orders) */
    for (k = 0; k < n / 900; k++) {
        x = 4 + rnd_n(MAP_W - 8);
        y = 4 + rnd_n(MAP_H - 8);
        blob(x, y, 30 + rnd_n(30), T_WATER);
    }
    for (k = 0; k < n / 280; k++) {
        int t, len;
        x = 2 + rnd_n(MAP_W - 4);
        y = 2 + rnd_n(MAP_H - 4);
        len = 10 + rnd_n(30);
        t = rnd_n(3) ? T_TREE : T_TREE2;
        blob(x, y, len, t);
    }
    for (k = 0; k < n / 160; k++) {
        x = 1 + rnd_n(MAP_W - 2);
        y = 1 + rnd_n(MAP_H - 2);
        put(x, y, rnd_n(2) ? T_ROCK : T_ROCK2);
    }
    /* a river from top to bottom, wandering, with two sandy fords whose
       banks are clear */
    x = river_x = MAP_W / 2 - 3 + rnd_n(6);
    for (y = 1; y < MAP_H - 1; y++) {
        int ford = y == MAP_H / 3 || y == MAP_H / 3 + 1 || y == 2 * MAP_H / 3 ||
                   y == 2 * MAP_H / 3 + 1;
        put(x, y, ford ? T_SAND : T_WATER);
        put(x + 1, y, ford ? T_SAND2 : T_WATER);
        if (ford && (y == MAP_H / 3 || y == 2 * MAP_H / 3)) {
            ford_x[f] = x;
            ford_y[f++] = y;
            clear_round(x - 1, y);
            clear_round(x + 2, y);
        }
        if ((y & 3) == 0)
            x += rnd_n(3) - 1;
    }
    /* the halls, in clearings at opposite corners */
    base_x[0] = 6;
    base_y[0] = 5;
    base_x[1] = MAP_W - 8;
    base_y[1] = MAP_H - 8;
    for (k = 0; k < 2; k++) {
        for (y = base_y[k] - 5; y <= base_y[k] + 7; y++)
            for (x = base_x[k] - 5; x <= base_x[k] + 6; x++)
                if (x > 0 && y > 0 && x < MAP_W - 1 && y < MAP_H - 1 &&
                    !is_water(map[CELL(x, y)]))
                    map[CELL(x, y)] = rnd() & 3 ? T_GRASS : T_GRASS3;
        for (y = 0; y < 3; y++)
            for (x = 0; x < 3; x++)
                map[CELL(base_x[k] - 1 + x, base_y[k] - 1 + y)] = T_BASE + 9 * k + 3 * y + x;
    }
    /* a wall of trees round the edge */
    for (x = 0; x < MAP_W; x++) {
        map[CELL(x, 0)] = T_TREE;
        map[CELL(x, MAP_H - 1)] = T_TREE;
    }
    for (y = 0; y < MAP_H; y++) {
        map[CELL(0, y)] = T_TREE;
        map[CELL(MAP_W - 1, y)] = T_TREE2;
    }
    /* In one pass: each water cell's shore (which sides are land), sand
       on a third of the land beside it, and what's walkable. Sand goes
       only where it was walkable, so the cells behind are still right;
       the edge is trees, so a water cell's neighbours are on the map. */
    for (k = 0; k < n; k++) {
        if (map[k] == T_WATER) {
            static const int side[4] = { -MAP_W, 1, MAP_W, -1 };
            int i, c, s = 0;
            for (i = 0; i < 4; i++) {
                c = k + side[i];
                if (is_water(map[c]))
                    continue;
                s |= 1 << i;
                if (!blocking[map[c]] && map[c] != T_SAND && map[c] != T_SAND2 &&
                    rnd_n(3) == 0)
                    map[c] = rnd() & 1 ? T_SAND : T_SAND2;
            }
            map[k] = T_WATER + s;
        }
        pass[k] = !blocking[map[k]];
    }
}

/* ---- flow fields ----
   A breadth-first search from the target over the walkable cells, four
   neighbours a step; a unit then steps to whichever of its eight
   neighbours is nearest. The search runs a few hundred cells a tick:
   until it reaches a unit, the unit heads straight for the target. */

static int field_age[NFIELD], field_clock;

int field_new(int tx, int ty)
{
    Field *f;
    int k, best = -1, r;
    /* a target in water or a forest: the nearest walkable cell */
    for (r = 1; r < 8 && !walkable(tx, ty); r++) {
        int dx, dy, found = 0;
        for (dy = -r; dy <= r && !found; dy++)
            for (dx = -r; dx <= r && !found; dx++)
                if (walkable(tx + dx, ty + dy)) {
                    tx += dx;
                    ty += dy;
                    found = 1;
                }
    }
    if (!walkable(tx, ty))
        return -1;
    /* a free field, else the oldest */
    for (k = 0; k < NFIELD; k++)
        if (fields[k].users == 0 && (best < 0 || field_age[k] < field_age[best]))
            best = k;
    if (best < 0)
        for (k = 0; k < NFIELD; k++)
            if (best < 0 || field_age[k] < field_age[best])
                best = k;
    f = &fields[best];
    f->dist = field_dist[best];
    f->queue = field_queue[best];
    memset(f->dist, 0xFF, sizeof field_dist[0]);
    f->tx = tx;
    f->ty = ty;
    f->dist[CELL(tx, ty)] = 0;
    f->queue[0] = CELL(tx, ty);
    f->head = 0;
    f->tail = 1;
    f->done = 0;
    f->users = 0;
    field_age[best] = ++field_clock;
    fields_made++;
    /* units still on it lose it */
    for (k = 0; k < nunits; k++)
        if (units[k].field == best)
            units[k].field = -1;
    return best;
}

void field_step(int budget)
{
    int k;
    for (k = 0; k < NFIELD && budget > 0; k++) {
        Field *f = &fields[k];
        unsigned short *dist = f->dist, *q = f->queue;
        int head = f->head, tail = f->tail;
        if (f->done || !dist)
            continue;
        field_cells -= head;
        while (head < tail && budget-- > 0) {
            int c = q[head++], d = dist[c] + 1, nb;
            /* the edge is all trees, so a walkable cell's neighbours are on the map */
            nb = c - MAP_W;
            if (dist[nb] == FIELD_FAR && pass[nb]) {
                dist[nb] = d;
                q[tail++] = nb;
            }
            nb = c + MAP_W;
            if (dist[nb] == FIELD_FAR && pass[nb]) {
                dist[nb] = d;
                q[tail++] = nb;
            }
            nb = c - 1;
            if (dist[nb] == FIELD_FAR && pass[nb]) {
                dist[nb] = d;
                q[tail++] = nb;
            }
            nb = c + 1;
            if (dist[nb] == FIELD_FAR && pass[nb]) {
                dist[nb] = d;
                q[tail++] = nb;
            }
        }
        field_cells += head;
        f->head = head;
        f->tail = tail;
        if (head >= tail)
            f->done = 1;
    }
}
