/* The units: workers that walk between their hall and the forest,
   soldiers, the enemy's guards walking round their hall, and what the
   player tells them. A unit walks from cell centre to cell centre down a
   flow field (map.c), and straight to its own place in a formation at
   the end; it plans its next step only when it reaches a waypoint, so
   most frames a unit costs two additions. */

#include <stdlib.h>
#include <string.h>
#include "rts.h"

Unit units[MAX_UNITS];
int nunits, nsel;

/* what a unit is doing beyond walking */
enum { J_IDLE, J_TO_WOOD, J_CHOP, J_TO_HALL, J_UNLOAD, J_PATROL, J_ORDER };
static unsigned char job[MAX_UNITS], patrol[MAX_UNITS];
static short slot_x[MAX_UNITS], slot_y[MAX_UNITS];    /* the goal, pixels from the field's target */

#define F_WOOD 0                /* the fields the workers share */
#define F_HALL 1

/* the formation: offsets in a spiral, 14 pixels apart */
#define NSLOT 64
static signed char spiral[NSLOT][2];

static int iabs(int v) { return v < 0 ? -v : v; }

/* about the length of (dx, dy): the octagon's, within 4 % */
static int vlen(int dx, int dy)
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

static int speed(const Unit *u) { return u->type == U_SOLDIER ? 20 : 16; }

/* head for (wx, wy), world pixels x 16, in a straight line */
static void head_for(Unit *u, int wx, int wy)
{
    int dx = wx - u->x, dy = wy - u->y, len = vlen(dx, dy), s = speed(u);
    if (len < s) {
        u->x = wx;
        u->y = wy;
        u->vx = u->vy = 0;
        u->wait = 0;
        return;
    }
    u->vx = dx * s / len;
    u->vy = dy * s / len;
    u->wait = len / s;
    if (u->vx)
        u->facing = u->vx < 0;
}

static void release(Unit *u)
{
    if (u->field >= 0 && fields[u->field].users > 0)
        fields[u->field].users--;
    u->field = -1;
}

static void follow(Unit *u, int f)
{
    release(u);
    u->field = f;
    fields[f].users++;
    u->moving = 1;
    u->wait = 0;
}

/* the next waypoint: down the field to the cell nearest the target, or
   straight on near the goal; 0 when it has arrived */
static int plan(Unit *u, int k)
{
    int tx = u->x >> 8, ty = u->y >> 8, c = ty * map_w + tx;
    Field *f;
    unsigned short *d;
    int gx, gy, best, bx = 0, by = 0, dx, dy;
    if (u->field < 0) {
        /* a straight walk: patrols, scattering; it stops at anything in the way */
        if (iabs(u->gx - u->x) < 16 && iabs(u->gy - u->y) < 16)
            return 0;
        head_for(u, u->gx, u->gy);
        if (u->wait > 16)
            u->wait = 16;
        return walkable((u->x + u->vx * 12) >> 8, (u->y + u->vy * 12) >> 8);
    }
    f = &fields[u->field];
    d = f->dist;
    gx = (f->tx * TILE + TILE / 2 + slot_x[k]) << 4;
    gy = (f->ty * TILE + TILE / 2 + slot_y[k]) << 4;
    if (iabs(gx - u->x) < 16 && iabs(gy - u->y) < 16)
        return 0;
    if (d[c] == FIELD_FAR && f->done)
        return 0;               /* no way there */
    if (d[c] == FIELD_FAR || vlen(gx - u->x, gy - u->y) < (2 * TILE) << 4) {
        /* the search hasn't come this far, or nearly there: straight on,
           unless the next cell that way is blocked */
        int nx, ny;
        head_for(u, gx, gy);
        nx = (u->x + u->vx * 12) >> 8;
        ny = (u->y + u->vy * 12) >> 8;
        if (!walkable(nx, ny) && d[c] != FIELD_FAR)
            goto down;
        if (!walkable(nx, ny)) {
            u->wait = 8;        /* wait for the search */
            u->vx = u->vy = 0;
        } else if (u->wait > 16) {
            u->wait = 16;       /* look again soon: the search may arrive */
        }
        return 1;
    }
down:
    best = d[c];
    for (dy = -1; dy <= 1; dy++)
        for (dx = -1; dx <= 1; dx++) {
            int n = c + dy * map_w + dx;
            if ((dx || dy) && d[n] < best && pass[n] &&
                (!dx || !dy || (pass[c + dx] && pass[c + dy * map_w]))) {
                best = d[n];
                bx = dx;
                by = dy;
            }
        }
    if (best == d[c]) {
        /* at the target's cell, its place unreachable: stop here */
        return 0;
    }
    head_for(u, ((tx + bx) * TILE + TILE / 2) << 4, ((ty + by) * TILE + TILE / 2) << 4);
    return 1;
}

/* a cell next to the forest near the hall, for the workers */
static void find_wood(int *wx, int *wy)
{
    int r, dx, dy, bx = base_x[0], by = base_y[0];
    for (r = 4; r < 20; r++)
        for (dy = -r; dy <= r; dy++)
            for (dx = -r; dx <= r; dx++) {
                int x = bx + dx, y = by + dy;
                /* not the wall of trees round the map's edge */
                if ((iabs(dx) == r || iabs(dy) == r) && walkable(x, y) && x > 1 && y > 1 &&
                    (map[y * map_w + x + 1] == T_TREE || map[y * map_w + x - 1] == T_TREE ||
                     map[(y + 1) * map_w + x] == T_TREE)) {
                    *wx = x;
                    *wy = y;
                    return;
                }
            }
    *wx = bx + 3;
    *wy = by + 3;
}

/* free walkable cells round (cx, cy), nearest first: the n-th */
static void place(Unit *u, int cx, int cy, int n)
{
    int r, dx, dy;
    for (r = 0; r < 30; r++)
        for (dy = -r; dy <= r; dy++)
            for (dx = -r; dx <= r; dx++)
                if ((iabs(dx) == r || iabs(dy) == r) && walkable(cx + dx, cy + dy) && n-- == 0) {
                    u->x = ((cx + dx) * TILE + 4 + rnd_n(8)) << 4;
                    u->y = ((cy + dy) * TILE + 6 + rnd_n(8)) << 4;
                    return;
                }
}

static int patrol_x(int k, int p) { return base_x[1] + (p == 1 || p == 2 ? 4 : -3) + (k & 1); }
static int patrol_y(int k, int p) { return base_y[1] + (p >= 2 ? 5 : -3) + (k >> 1 & 1); }

/* bench: n units in the viewport, each bouncing round it; else the game's */
void units_init(int n, int bench_mode)
{
    int k, wx, wy;
    spiral_make();
    memset(units, 0, sizeof units);
    nunits = n;
    nsel = 0;
    for (k = 0; k < n; k++) {
        Unit *u = &units[k];
        u->field = -1;
        u->hp = 40 + rnd_n(60);
        if (bench_mode) {
            u->type = k & 1;
            u->team = (k >> 1) % 3 == 2;
            u->x = (cam_x + 8 + rnd_n(view_w - 16)) << 4;
            u->y = (cam_y + 14 + rnd_n(view_h - 16)) << 4;
            u->vx = rnd_n(41) - 20;
            u->vy = rnd_n(41) - 20;
            u->moving = 1;
            u->facing = u->vx < 0;
            continue;
        }
        if (k < n * 3 / 4) {
            /* the player's: workers and soldiers round the hall */
            u->team = 0;
            u->type = k % 3 == 2 ? U_WORKER : U_SOLDIER;
            place(u, base_x[0] + 1, base_y[0] + 3, k);
            if (u->type == U_WORKER) {
                job[k] = J_TO_WOOD;
                u->wait = k * 7 % 90;   /* not all at once */
            }
        } else {
            /* the enemy's guards */
            u->team = 1;
            u->type = U_SOLDIER;
            patrol[k] = k & 3;
            u->x = ((patrol_x(k, patrol[k]) * TILE) + 8) << 4;
            u->y = ((patrol_y(k, patrol[k]) * TILE) + 8 + (k & 4) * 2) << 4;
            job[k] = J_PATROL;
            u->wait = k * 13 % 60;
        }
    }
    if (bench_mode)
        return;
    /* the workers' two fields, searched to the end now */
    find_wood(&wx, &wy);
    field_new(wx, wy);
    field_new(base_x[0], base_y[0] + 2);
    field_step(1 << 20);
    for (k = 0; k < n; k++) {
        slot_x[k] = rnd_n(9) - 4;
        slot_y[k] = rnd_n(7) - 3;
    }
}

/* a unit with nothing to walk to: its job's next step */
static void next_job(Unit *u, int k)
{
    switch (job[k]) {
    case J_TO_WOOD:
        follow(u, F_WOOD);
        job[k] = J_CHOP;
        break;
    case J_CHOP:
        release(u);
        u->moving = 0;
        u->wait = 90 + rnd_n(60);
        job[k] = J_TO_HALL;
        break;
    case J_TO_HALL:
        follow(u, F_HALL);
        job[k] = J_UNLOAD;
        break;
    case J_UNLOAD:
        release(u);
        u->moving = 0;
        u->wait = 30;
        job[k] = J_TO_WOOD;
        break;
    case J_PATROL:
        patrol[k] = (patrol[k] + 1) & 3;
        u->gx = ((patrol_x(k, patrol[k]) * TILE) + 8) << 4;
        u->gy = ((patrol_y(k, patrol[k]) * TILE) + 8) << 4;
        u->moving = 1;
        u->wait = 0;
        break;
    default:
        release(u);
        u->moving = 0;
        u->wait = 1 << 14;
        job[k] = J_IDLE;
        break;
    }
}

void units_update(int dt)
{
    int k;
    Unit *u = units;
    for (k = 0; k < nunits; k++, u++) {
        if (u->moving) {
            if (dt == 1) {
                u->x += u->vx;
                u->y += u->vy;
            } else {
                u->x += u->vx * dt;
                u->y += u->vy * dt;
            }
        }
        u->wait -= dt;
        if (u->wait > 0)
            continue;
        if (!u->moving || !plan(u, k)) {
            u->vx = u->vy = 0;
            if (u->moving) {
                u->moving = 0;
                u->wait = 0;
            }
            next_job(u, k);
        }
    }
    /* the walking animation: a step every 8 frames */
    u = units;
    for (k = 0; k < nunits; k++, u++)
        u->step = u->moving && ((frame_no + k) >> 3 & 1);
}

/* the benchmark's units: straight lines, bouncing off the viewport's edges */
void units_bench_update(int dt)
{
    int k, x0 = (cam_x + 8) << 4, x1 = (cam_x + view_w - 8) << 4;
    int y0 = (cam_y + 14) << 4, y1 = (cam_y + view_h - 2) << 4;
    Unit *u = units;
    for (k = 0; k < nunits; k++, u++) {
        u->x += u->vx;
        u->y += u->vy;
        if (u->x < x0 || u->x >= x1) {
            u->vx = -u->vx;
            u->x = u->x < x0 ? x0 : x1 - 1;
            u->facing = u->vx < 0;
        }
        if (u->y < y0 || u->y >= y1) {
            u->vy = -u->vy;
            u->y = u->y < y0 ? y0 : y1 - 1;
        }
        u->step = (frame_no + k) >> 3 & 1;
    }
}

/* n more soldiers round the player's hall, idle */
void units_spawn(int n)
{
    while (n-- > 0 && nunits < MAX_UNITS) {
        Unit *u = &units[nunits];
        memset(u, 0, sizeof *u);
        u->field = -1;
        u->type = U_SOLDIER;
        u->hp = 100;
        place(u, base_x[0] + 1, base_y[0] + 3, nunits);
        job[nunits] = J_IDLE;
        u->wait = 1 << 14;
        nunits++;
    }
}

void units_command(int wx, int wy)
{
    int f = -1, k, n = 0;
    if (!nsel)
        return;
    /* the workers' fields stay theirs */
    fields[F_WOOD].users += 1000;
    fields[F_HALL].users += 1000;
    f = field_new(wx / TILE, wy / TILE);
    fields[F_WOOD].users -= 1000;
    fields[F_HALL].users -= 1000;
    if (f < 0)
        return;
    for (k = 0; k < nunits; k++) {
        Unit *u = &units[k];
        int s, gx, gy;
        if (!u->sel)
            continue;
        /* its place: the next spiral slot whose cell is walkable */
        for (s = n; s < NSLOT; s++) {
            gx = fields[f].tx * TILE + TILE / 2 + spiral[s][0] * 14;
            gy = fields[f].ty * TILE + TILE / 2 + spiral[s][1] * 14;
            if (walkable(gx / TILE, gy / TILE))
                break;
        }
        if (s == NSLOT)
            s = 0;
        n = s + 1;
        slot_x[k] = spiral[s][0] * 14;
        slot_y[k] = spiral[s][1] * 14;
        job[k] = J_ORDER;
        follow(u, f);
    }
}

void units_select(int x0, int y0, int x1, int y1, int add)
{
    int k, best = -1, bd = 1 << 30, click = x1 - x0 < 4 && y1 - y0 < 4;
    nsel = 0;
    for (k = 0; k < nunits; k++) {
        Unit *u = &units[k];
        int x = u->x >> 4, y = (u->y >> 4) - 5;
        if (!add)
            u->sel = 0;
        if (u->team)
            continue;
        if (click) {
            int d = iabs(x - x0) + iabs(y - y0);
            if (d < 10 && d < bd) {
                bd = d;
                best = k;
            }
        } else if (x >= x0 && x < x1 && y >= y0 && y < y1) {
            u->sel = 1;
        }
    }
    if (best >= 0)
        units[best].sel = 1;
    for (k = 0; k < nunits; k++)
        nsel += units[k].sel;
}

void units_stop(void)
{
    int k;
    for (k = 0; k < nunits; k++)
        if (units[k].sel) {
            release(&units[k]);
            units[k].moving = 0;
            units[k].vx = units[k].vy = 0;
            units[k].wait = 1 << 14;
            job[k] = J_IDLE;
        }
}

void units_scatter(void)
{
    int k;
    for (k = 0; k < nunits; k++) {
        Unit *u = &units[k];
        int n, gx, gy;
        if (!u->sel)
            continue;
        for (n = 0; n < 8; n++) {
            gx = (u->x >> 4) + rnd_n(97) - 48;
            gy = (u->y >> 4) + rnd_n(97) - 48;
            if (walkable(gx / TILE, gy / TILE))
                break;
        }
        if (n == 8)
            continue;
        release(u);
        u->gx = gx << 4;
        u->gy = gy << 4;
        u->moving = 1;
        u->wait = 0;
        job[k] = J_ORDER;
    }
}
