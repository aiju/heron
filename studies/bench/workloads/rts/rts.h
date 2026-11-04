/* A real-time strategy game's logic, headless: the game of Heron Mini's
   RTS (studies/mini_gfx/games/rts on its branch) without its drawing.
   A tile map with a river, fords, lakes and forests; two teams of units
   in groups, given scripted orders; flow fields searched breadth-first
   from each order's target, a few hundred cells a tick; formations;
   steering on an occupancy grid; the nearest enemy found through spatial
   buckets; combat, arrows and deaths; and the bookkeeping a frame needs
   before anything is drawn (the units in drawing order, the dirty
   tiles, the minimap).

   Everything is integers. Positions are world pixels x 16, so a tile
   (16 pixels) is 256 position units. The size parameters: MAP_W x MAP_H
   tiles, NUNITS units, TICKS ticks, a report every REPORT ticks. */

#ifndef RTS_H
#define RTS_H

#define TILE 16                 /* pixels */
#define TSHIFT 8                /* a position >> TSHIFT is its tile */
#define MAP_N (MAP_W * MAP_H)
#define CELL(x, y) ((y) * MAP_W + (x))

/* ---- the PRNG (game.c): the C library's rand() differs between the
   machine and the host, so the game has its own ---- */
extern unsigned rng_state;
unsigned rnd(void);
int rnd_n(int n);               /* 0 .. n-1 */

int iabs(int v);
/* about the length of (dx, dy): the octagon's, within 4 % */
int vlen(int dx, int dy);

/* ---- the map (map.c) ---- */
enum {
    T_GRASS, T_GRASS2, T_GRASS3, T_GRASS4, T_SAND, T_SAND2, T_TREE, T_TREE2, T_ROCK, T_ROCK2,
    T_FLOWER, T_WATER,                  /* + 16 shore variants: T_WATER + land sides (NESW) */
    T_BASE = T_WATER + 16,              /* + 9 a team: a 3 x 3 building */
    T_N = T_BASE + 18
};
extern unsigned char map[MAP_N];        /* the tile of each cell */
extern unsigned char pass[MAP_N];       /* 1: walkable */
extern unsigned char decal[MAP_N];      /* the fallen on each cell, drawn over its tile */
extern int base_x[2], base_y[2];        /* the teams' halls, the centre cell */
extern int ford_x[2], ford_y[2];        /* the river's two fords, their west cell */
extern int river_x;                     /* about where the river runs */

void map_make(unsigned seed);
int walkable(int tx, int ty);

/* flow fields: the distance (in steps) of each cell from a target, by a
   breadth-first search spread over ticks */
#define NFIELD 8
#define FIELD_FAR 0xFFFF
typedef struct {
    unsigned short *dist;       /* MAP_N */
    unsigned short *queue;
    int head, tail;
    int tx, ty;                 /* the target cell */
    int users;                  /* units following it */
    int done;
} Field;
extern Field fields[NFIELD];
extern int fields_made, field_cells;
int field_new(int tx, int ty);  /* a field's number, or -1 if there's nowhere to go */
void field_step(int budget);    /* advance the searches by `budget` cells */

/* ---- units (units.c) ---- */
enum { U_WORKER, U_SOLDIER, U_ARCHER, U_NTYPES };

/* what a unit is doing */
enum {
    S_IDLE,                     /* standing; fights what comes into range */
    S_MOVE,                     /* going where it was told, whatever it meets */
    S_AMOVE,                    /* going there, but fighting what it sees on the way */
    S_FIGHT,                    /* chasing and hitting its target */
    S_TO_WOOD, S_CHOP, S_TO_HALL, S_UNLOAD,     /* a worker's round */
    S_DEAD
};

/* 32 bytes: the C compiler indexes arrays of other sizes with a multiply */
typedef struct {
    int x, y;                   /* the feet, world pixels x 16 */
    short gx, gy;               /* a straight walk's goal, world pixels x 16 */
    short vx, vy;               /* this tick's velocity, pixels x 16 */
    short field;                /* the flow field it follows, or -1 */
    short wait;                 /* ticks before it plans its next step */
    short target;               /* the unit it fights, or -1 */
    unsigned char hp, type, team, state;
    unsigned char after;        /* the state its walk ends in */
    unsigned char anim;         /* bit 0: facing left; bit 1: the step of its walk */
    unsigned char cool;         /* ticks to its next blow */
    unsigned char blocked;      /* ticks it has been unable to step */
    unsigned char group, pad;
} Unit;

#define MAX_UNITS 320
extern Unit units[MAX_UNITS];
extern int nunits;
extern int alive[2];

/* what each type is */
typedef struct {
    short hp, speed;            /* speed: pixels x 16 a tick */
    short range, damage;        /* range: pixels x 16 */
    short cooldown, sight;      /* sight: pixels x 16 */
} UnitType;
extern const UnitType utypes[U_NTYPES];

/* the occupancy grid: a cell of OCELL pixels holds at most one unit, and
   says which (index + 1), 0 when free */
#define OCELL 8
#define OSHIFT 7                /* a position >> OSHIFT is its cell */
#define OCC_W (MAP_W * 2)
#define OCC_H (MAP_H * 2)
extern unsigned short occ[OCC_W * OCC_H];

void units_init(void);
/* a unit of a type at the nearest free walkable cell round (cx, cy):
   its index, or -1 */
int unit_add(int type, int team, int group, int cx, int cy);
/* an order to a group of a team: walk to cell (tx, ty) in formation;
   fighting what it meets on the way if amove */
void units_order(int team, int group, int tx, int ty, int amove);
void units_think(int tick);     /* targets, plans and steps, each unit */
void unit_release(Unit *u);     /* stop following its field */
void unit_steer(Unit *u, int k);        /* move by its velocity, round others */
void unit_head_for(Unit *u, int wx, int wy);
extern int steps_blocked, side_steps;

/* ---- combat (combat.c) ---- */
void buckets_build(void);
int nearest_enemy(const Unit *u, int range);    /* index, or -1 */
void combat(Unit *u, int k);    /* a fighting unit's tick: chase or strike */
void arrows_fly(void);
void deaths(void);
extern int blows, arrows, kills[2];

/* ---- the frame's bookkeeping (view.c) ---- */
#define VIEW_W 640              /* the viewport, pixels */
#define VIEW_H 400
extern int cam_x, cam_y;        /* its top left in the world */
void view_init(void);
void view_frame(int tick);      /* what would be drawn this frame */
void minimap_init(void);       /* the terrain's colours, once the map is made */
void minimap_fallen(int c);     /* a unit fell on cell c */
void minimap_make(void);
unsigned minimap_hash(void);    /* a checksum of every minimap made */
extern unsigned frame_sum;      /* a checksum of every frame's drawing list */
extern int dirty_tiles, items_drawn, minimaps;

/* a tile to be drawn again, if it's in view (a unit fell on it) */
void tile_dirty(int tx, int ty);

#endif
