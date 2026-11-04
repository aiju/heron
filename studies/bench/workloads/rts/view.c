/* The frame's bookkeeping: what a renderer needs worked out before it
   draws anything, from studies/mini_gfx/games/rts/render.c on Heron
   Mini's branch (the drawing itself is another workload's):

   - the units in order of their feet's y, so nearer ones are drawn over
     farther ones: sorted again each frame, by insertion since they
     barely move;
   - the drawing list: the units in the viewport, each with its sprite
     (type, team, facing, step of its walk, wounded or not);
   - the dirty tiles: where a unit was drawn last frame and has moved
     from, or has moved to, or has fallen; a renderer redraws those
     tiles and then every unit that touches one;
   - every fourth frame, the minimap: a pixel a tile, the units on it in
     their team's colours, and the viewport's outline.

   The camera stays on the first ford, where the fighting is. */

#include "rts.h"

int cam_x, cam_y;
unsigned frame_sum;
int dirty_tiles, items_drawn, minimaps;

/* the viewport's tiles; the camera is on a tile, so they line up */
#define VT_W (VIEW_W / TILE)
#define VT_H (VIEW_H / TILE)
static unsigned char dirty[VT_H * VT_W];
static short dirty_list[VT_H * VT_W];
static int ndirty;

/* the units, nearest last, and their feet's y as sorted */
static unsigned short order[MAX_UNITS];
static int ykey[MAX_UNITS];
static int norder;

/* a unit as it will be drawn: its sprite's 16 x 16 cell in the world */
typedef struct {
    short x, y;
    short sprite, unit;
} Item;
static Item items[MAX_UNITS];
static int nitems;

/* where each unit was drawn last frame, and as what; drawn_y < 0: not */
static short drawn_x[MAX_UNITS], drawn_y[MAX_UNITS], drawn_s[MAX_UNITS];

/* type (3) x team (2) x facing (2) x step (2) x wounded (2) */
#define SPR_INDEX(ty, tm, f, st, w) (((((ty) * 2 + (tm)) * 2 + (f)) * 2 + (st)) * 2 + (w))

/* the camera's top left tile */
static int cam_tx, cam_ty;

#define MARK(c)                                                         \
    do {                                                                \
        if (!dirty[c]) {                                                \
            dirty[c] = 1;                                               \
            dirty_list[ndirty++] = (c);                                 \
        }                                                               \
    } while (0)

void tile_dirty(int tx, int ty)
{
    int c;
    tx -= cam_tx;
    ty -= cam_ty;
    if (tx >= 0 && ty >= 0 && tx < VT_W && ty < VT_H) {
        c = ty * VT_W + tx;
        MARK(c);
    }
}

/* the tiles under a sprite cell at world pixel (px, py): one to four */
static void cell_dirty(int px, int py)
{
    int tx = (px >> 4) - cam_tx, ty = (py >> 4) - cam_ty, c;
    if (tx < 0 || ty < 0 || tx >= VT_W - 1 || ty >= VT_H - 1) {
        /* at the viewport's edges, or out of it: tile by tile */
        tx += cam_tx;
        ty += cam_ty;
        tile_dirty(tx, ty);
        if (px & 15)
            tile_dirty(tx + 1, ty);
        if (py & 15) {
            tile_dirty(tx, ty + 1);
            if (px & 15)
                tile_dirty(tx + 1, ty + 1);
        }
        return;
    }
    c = ty * VT_W + tx;
    MARK(c);
    if (px & 15) {
        c++;
        MARK(c);
        c--;
    }
    if (py & 15) {
        c += VT_W;
        MARK(c);
        if (px & 15) {
            c++;
            MARK(c);
        }
    }
}

/* does a sprite cell in view touch a dirty tile? */
static int touches_dirty(int px, int py)
{
    int tx = (px >> 4) - cam_tx, ty = (py >> 4) - cam_ty, x, y, x1, y1;
    x1 = (px & 15) ? tx + 1 : tx;
    y1 = (py & 15) ? ty + 1 : ty;
    if (tx < 0)
        tx = 0;
    if (ty < 0)
        ty = 0;
    if (x1 >= VT_W)
        x1 = VT_W - 1;
    if (y1 >= VT_H)
        y1 = VT_H - 1;
    for (y = ty; y <= y1; y++)
        for (x = tx; x <= x1; x++)
            if (dirty[y * VT_W + x])
                return 1;
    return 0;
}

static int clamp(int v, int lo, int hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

void view_init(void)
{
    int k;
    cam_x = clamp(ford_x[0] * TILE + TILE - VIEW_W / 2, 0, MAP_W * TILE - VIEW_W);
    cam_y = clamp(ford_y[0] * TILE + TILE - VIEW_H / 2, 0, MAP_H * TILE - VIEW_H);
    if (cam_x < 0)
        cam_x = 0;              /* a map smaller than the screen */
    if (cam_y < 0)
        cam_y = 0;
    cam_x &= ~(TILE - 1);
    cam_y &= ~(TILE - 1);
    cam_tx = cam_x / TILE;
    cam_ty = cam_y / TILE;
    for (k = 0; k < MAX_UNITS; k++)
        drawn_y[k] = -1;
    ndirty = 0;
    norder = 0;
}

static void sort_units(void)
{
    int k, j;
    if (norder != nunits) {
        for (k = 0; k < nunits; k++)
            order[k] = k;
        norder = nunits;
    }
    for (k = 0; k < norder; k++)
        ykey[k] = units[k].y;
    for (k = 1; k < norder; k++) {
        unsigned o = order[k];
        int y = ykey[o];
        for (j = k; j > 0 && ykey[order[j - 1]] > y; j--)
            order[j] = order[j - 1];
        order[j] = o;
    }
}

void view_frame(int tick)
{
    int k, i, px, py, s, visible;
    unsigned sum = 0;
    sort_units();
    nitems = 0;
    for (k = 0; k < norder; k++) {
        const Unit *u;
        i = order[k];
        u = &units[i];
        if (u->state == S_DEAD) {
            if (drawn_y[i] >= 0)
                cell_dirty(drawn_x[i], drawn_y[i]);
            drawn_y[i] = -1;
            continue;
        }
        px = (u->x >> 4) - TILE / 2;
        py = (u->y >> 4) - TILE + 1;
        s = SPR_INDEX(u->type, u->team, u->anim & 1, (u->anim >> 1) & 1,
                      2 * u->hp < utypes[u->type].hp);
        visible = px + TILE > cam_x && px < cam_x + VIEW_W && py + TILE > cam_y &&
                  py < cam_y + VIEW_H;
        if (px == drawn_x[i] && py == drawn_y[i] && s == drawn_s[i]) {
            /* as it was: drawn again only if something dirtied its tiles */
        } else {
            if (drawn_y[i] >= 0)
                cell_dirty(drawn_x[i], drawn_y[i]);
            if (visible)
                cell_dirty(px, py);
        }
        if (!visible) {
            drawn_y[i] = -1;
            continue;
        }
        items[nitems].x = px;
        items[nitems].y = py;
        items[nitems].sprite = s;
        items[nitems].unit = i;
        nitems++;
        drawn_x[i] = px;
        drawn_y[i] = py;
        drawn_s[i] = s;
    }
    /* the redraw: the dirty tiles, then the units that touch them, in order */
    for (k = 0; k < nitems; k++) {
        const Item *it = &items[k];
        if (touches_dirty(it->x, it->y)) {
            sum = sum * 31 + ((it->y << 16) ^ (it->x << 6) ^ it->sprite);
            items_drawn++;
        }
    }
    for (k = 0; k < ndirty; k++) {
        sum += dirty_list[k];
        dirty[dirty_list[k]] = 0;
    }
    dirty_tiles += ndirty;
    ndirty = 0;
    frame_sum = frame_sum * 33 + sum;
    if ((tick & 3) == 1)
        minimap_make();
}

/* ---- the minimap ----
   A pixel a tile: the terrain, made once and marked where units fall,
   copied each time, and the units and the viewport drawn over it. Both
   are kept in words, to be copied and hashed a word at a time. */

#define MM_WORDS ((MAP_N + 3) / 4)
static unsigned terrain_words[MM_WORDS], minimap_words[MM_WORDS];
#define terrain ((unsigned char *)terrain_words)
#define minimap ((unsigned char *)minimap_words)
static unsigned minimap_sum;

#define C_FALLEN 0x44

/* a tile's colour, from a 3-3-2 palette */
static unsigned char tile_colour(int t)
{
    if (t <= T_GRASS4)
        return 0x14 + (t & 1) * 4;      /* greens */
    if (t == T_FLOWER)
        return 0x18;
    if (t <= T_SAND2)
        return 0xD6;
    if (t <= T_TREE2)
        return 0x0C;
    if (t <= T_ROCK2)
        return 0x92;
    if (t < T_BASE)
        return 0x07 + (t == T_WATER ? 0 : 0x20);       /* water, shores lighter */
    return t < T_BASE + 9 ? 0xE3 : 0x63;
}

void minimap_init(void)
{
    unsigned char palette[T_N];
    int k;
    for (k = 0; k < T_N; k++)
        palette[k] = tile_colour(k);
    for (k = 0; k < MAP_N; k++)
        terrain[k] = palette[map[k]];
}

void minimap_fallen(int c)
{
    terrain[c] = C_FALLEN;
}

void minimap_make(void)
{
    int k, x, y, x1, y1;
    const Unit *u = units;
    unsigned h = 5381;
    for (k = 0; k < MM_WORDS; k++)
        minimap_words[k] = terrain_words[k];
    for (k = 0; k < nunits; k++, u++)
        if (u->state != S_DEAD)
            minimap[CELL(u->x >> TSHIFT, u->y >> TSHIFT)] = u->team ? 0xE0 : 0xFF;
    /* the viewport's outline */
    x1 = (cam_x + VIEW_W) / TILE - 1;
    y1 = (cam_y + VIEW_H) / TILE - 1;
    if (x1 >= MAP_W)
        x1 = MAP_W - 1;
    if (y1 >= MAP_H)
        y1 = MAP_H - 1;
    for (x = cam_tx; x <= x1; x++)
        minimap[CELL(x, cam_ty)] = minimap[CELL(x, y1)] = 0xFC;
    for (y = cam_ty; y <= y1; y++)
        minimap[CELL(cam_tx, y)] = minimap[CELL(x1, y)] = 0xFC;
    /* its checksum, a word at a time */
    for (k = 0; k < MM_WORDS; k++)
        h = ((h << 5) + h) ^ minimap_words[k];
    minimap_sum = minimap_sum * 33 + h;
    minimaps++;
}

/* a checksum of every minimap made so far */
unsigned minimap_hash(void)
{
    return minimap_sum;
}
