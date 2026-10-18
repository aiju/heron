/* The map: made from a seed (grass, lakes, a river with fords, forests,
   rocks, two bases), drawn once into the world bitmaps, and searched
   for paths with flow fields. */

#include <stdlib.h>
#include <string.h>
#include "rts.h"

int map_w, map_h, world_w, world_h, wpitch;
unsigned char *map, *pass;
unsigned *world[2], *clean;
int *wrowo;
int base_x[2], base_y[2];
Field fields[NFIELD];

#define CELL(x, y) ((y) * map_w + (x))

static int is_water(int t) { return t >= T_WATER && t < T_WATER + 16; }

static int blocks(int t)
{
    return t == T_TREE || t == T_TREE2 || t == T_ROCK || t == T_ROCK2 || is_water(t) ||
           t >= T_BASE;
}

int walkable(int tx, int ty)
{
    if (tx < 0 || ty < 0 || tx >= map_w || ty >= map_h)
        return 0;
    return pass[CELL(tx, ty)];
}

static void put(int x, int y, int t)
{
    if (x > 0 && y > 0 && x < map_w - 1 && y < map_h - 1)
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

void map_make(unsigned seed)
{
    int x, y, k, n = map_w * map_h;
    rng_state = seed;
    map = malloc(n);
    pass = malloc(n);
    /* grass, a little varied, flowers here and there */
    for (k = 0; k < n; k++) {
        int r = rnd_n(16);
        map[k] = r < 8 ? T_GRASS : r < 11 ? T_GRASS2 : r < 14 ? T_GRASS3 : r < 15 ? T_GRASS4
                                                                                   : T_FLOWER;
    }
    /* a river from top to bottom, wandering, with two sandy fords */
    x = map_w / 2 - 3 + rnd_n(6);
    for (y = 1; y < map_h - 1; y++) {
        int ford = y == map_h / 3 || y == map_h / 3 + 1 || y == 2 * map_h / 3 ||
                   y == 2 * map_h / 3 + 1;
        put(x, y, ford ? T_SAND : T_WATER);
        put(x + 1, y, ford ? T_SAND2 : T_WATER);
        if ((y & 3) == 0)
            x += rnd_n(3) - 1;
    }
    /* lakes, forests, rocks */
    for (k = 0; k < map_w * map_h / 900; k++)
        blob(4 + rnd_n(map_w - 8), 4 + rnd_n(map_h - 8), 30 + rnd_n(30), T_WATER);
    for (k = 0; k < map_w * map_h / 280; k++)
        blob(2 + rnd_n(map_w - 4), 2 + rnd_n(map_h - 4), 10 + rnd_n(30),
             rnd_n(3) ? T_TREE : T_TREE2);
    for (k = 0; k < map_w * map_h / 160; k++)
        put(1 + rnd_n(map_w - 2), 1 + rnd_n(map_h - 2), rnd_n(2) ? T_ROCK : T_ROCK2);
    /* sand beside some water */
    for (y = 1; y < map_h - 1; y++)
        for (x = 1; x < map_w - 1; x++)
            if (!blocks(map[CELL(x, y)]) && rnd_n(3) == 0 &&
                (map[CELL(x - 1, y)] == T_WATER || map[CELL(x + 1, y)] == T_WATER ||
                 map[CELL(x, y - 1)] == T_WATER || map[CELL(x, y + 1)] == T_WATER))
                map[CELL(x, y)] = rnd_n(2) ? T_SAND : T_SAND2;
    /* the bases, in clearings at opposite corners */
    base_x[0] = 6;
    base_y[0] = 5;
    base_x[1] = map_w - 8;
    base_y[1] = map_h - 8;
    for (k = 0; k < 2; k++) {
        for (y = base_y[k] - 5; y <= base_y[k] + 7; y++)
            for (x = base_x[k] - 5; x <= base_x[k] + 6; x++)
                if (x > 0 && y > 0 && x < map_w - 1 && y < map_h - 1)
                    map[CELL(x, y)] = rnd_n(4) ? T_GRASS : T_GRASS3;
        for (y = 0; y < 3; y++)
            for (x = 0; x < 3; x++)
                map[CELL(base_x[k] - 1 + x, base_y[k] - 1 + y)] = T_BASE + 9 * k + 3 * y + x;
    }
    /* a wall of trees round the edge */
    for (x = 0; x < map_w; x++) {
        map[CELL(x, 0)] = T_TREE;
        map[CELL(x, map_h - 1)] = T_TREE;
    }
    for (y = 0; y < map_h; y++) {
        map[CELL(0, y)] = T_TREE;
        map[CELL(map_w - 1, y)] = T_TREE2;
    }
    /* the water's shores: which sides are land */
    for (y = 0; y < map_h; y++)
        for (x = 0; x < map_w; x++)
            if (map[CELL(x, y)] == T_WATER) {
                int s = 0;
                if (y > 0 && !is_water(map[CELL(x, y - 1)]))
                    s |= 1;
                if (x < map_w - 1 && !is_water(map[CELL(x + 1, y)]))
                    s |= 2;
                if (y < map_h - 1 && !is_water(map[CELL(x, y + 1)]))
                    s |= 4;
                if (x > 0 && !is_water(map[CELL(x - 1, y)]))
                    s |= 8;
                map[CELL(x, y)] = T_WATER + s;
            }
    for (k = 0; k < n; k++)
        pass[k] = !blocks(map[k]);
}

/* the world bitmaps: each cell's tile into the first, then copied to the
   second and to the clean copy in bank 0 */
void world_draw(void)
{
    int x, y, tw = TILE / ppw;
    for (y = 0; y < map_h; y++)
        for (x = 0; x < map_w; x++)
            k_tile(world[0] + wrowo[y * TILE] + x * tw, tiles + map[CELL(x, y)] * tile_words, tw,
                   wpitch * 4);
    k_copy(clean, world[0], wpitch, world_h, wpitch * 4, wpitch * 4);
    if (world[1] != world[0])
        k_copy(world[1], world[0], wpitch, world_h, wpitch * 4, wpitch * 4);
}

/* ---- flow fields ----
   A breadth-first search from the target over the walkable cells, four
   neighbours a step; a unit then steps to whichever of its eight
   neighbours is nearest. The search runs a few hundred cells a frame:
   until it reaches a unit, the unit heads straight for the target. */

static int field_age[NFIELD], field_clock;

int field_new(int tx, int ty)
{
    Field *f;
    int k, best = -1, n = map_w * map_h, r;
    /* a target in water or a forest: the nearest walkable cell */
    for (r = 0; r < 8 && !walkable(tx, ty); r++) {
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
    if (!f->dist) {
        f->dist = malloc(n * 2);
        f->queue = malloc(n * 2);
    }
    memset(f->dist, 0xFF, n * 2);
    f->tx = tx;
    f->ty = ty;
    f->dist[CELL(tx, ty)] = 0;
    f->queue[0] = CELL(tx, ty);
    f->head = 0;
    f->tail = 1;
    f->done = 0;
    f->users = 0;
    field_age[best] = ++field_clock;
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
        int head = f->head, tail = f->tail, w = map_w;
        if (f->done || !dist)
            continue;
        while (head < tail && budget-- > 0) {
            int c = q[head++], d = dist[c] + 1, nb;
            /* the edge is all trees, so a walkable cell's neighbours are on the map */
            nb = c - w;
            if (dist[nb] == FIELD_FAR && pass[nb]) {
                dist[nb] = d;
                q[tail++] = nb;
            }
            nb = c + w;
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
        f->head = head;
        f->tail = tail;
        if (head >= tail)
            f->done = 1;
    }
}
