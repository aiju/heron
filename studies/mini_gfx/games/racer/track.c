/* The track, and the projection that turns it into each screen line's
   road row, start and stripe (racer.h).

   The track is a lap of 4096 entries of 32 world units: each entry's
   curvature and height, from a list of sections. Integrating the
   curvature gives the road's heading A and its lateral position P along
   the lap; the projection looks at the road from just behind the
   player's car, turned to the road's heading there.

   The projection steps through the 256 distances d at which flat ground
   would show road row d - 1 (z = PROJ / d), from the nearest. At each it
   finds the screen line the road there is on (lower or higher with the
   hills: one multiply), its centre's screen x (the curve and the
   player's offset: one multiply), and its stripe. A step that lands
   above the lines already filled fills the lines up to them with its
   row, repeating it if there's a gap; one that lands below is hidden
   behind a crest. So the hills are rows repeated and skipped, the curves
   start addresses, the stripes palette banks. */

#include <string.h>
#include "racer.h"

short trk_curve[TLEN];
short trk_height[TLEN];
int trk_pos[TLEN + 1];          /* P: the road's lateral position, world units / 16 */
static int trk_head[TLEN + 1];  /* A: its heading, world units x 256 an entry */
int drift;                      /* P's change over a lap (the heading's is 0) */
int zt[NROWS + 1];
SegObj seg_obj[NSEG];
Car cars[NCARS];

unsigned line_info[NLINES];
short step_yc[2 * (NROWS + 2)], step_sx[NROWS + 2];
unsigned kinfo[NROWS + 1];      /* a road line's information but the centre and stripe: (d - 1) << 8 | LK_ROAD */
int road_top;

/* a section: entering, holding and leaving its curve (in segments), the
   curvature (world units x 256 an entry, an entry), the height it climbs */
static const short sections[][5] = {
    {0, 30, 0, 0, 0},           /* the start */
    {10, 30, 10, 14, 0},        /* a long right */
    {10, 10, 10, 0, 2200},      /* up a hill */
    {10, 20, 10, -22, -900},    /* a left over the crest, going down */
    {0, 20, 0, 0, 0},
    {6, 10, 6, 30, 0},          /* an S */
    {6, 10, 6, -30, 0},
    {0, 40, 0, 0, -2600},       /* down into a dip */
    {0, 40, 0, 0, 2600},        /* and out of it */
    {10, 40, 10, 12, 1500},     /* a climbing right */
    {0, 20, 0, 0, -1600},       /* a crest */
    {10, 30, 10, 0, 0},         /* a left: its curvature closes the lap's heading */
    {0, 0, 0, 0, 0},            /* the rest, straight, back to height 0 */
};
#define NSECT (sizeof sections / sizeof sections[0])
#define CLOSING (NSECT - 2)

/* smoothstep, t of 256: 0..256 */
static int ease(int t)
{
    return (t * t * (768 - 2 * t)) >> 16;
}

static unsigned rng = 12345;
static int rnd(int n)
{
    rng = rng * 1103515245 + 12345;
    return (rng >> 16) % n;
}

/* the entries of one section from entry e, its height starting at h0;
   returns the height it ends at */
static int section(int e, const short *s, int curve, int n_all, int h0)
{
    int enter = s[0] * 8, hold = s[1] * 8, leave = s[2] * 8, j, n = enter + hold + leave;
    if (n_all)
        n = n_all, hold = n - enter - leave;
    for (j = 0; j < n; j++) {
        int c = curve;
        if (j < enter)
            c = curve * j / enter;
        else if (j >= enter + hold)
            c = curve * (n - j) / leave;
        trk_curve[(e + j) & TMASK] = c;
        trk_height[(e + j) & TMASK] = h0 + s[4] * ease(j * 256 / n) / 256;
    }
    return h0 + s[4];
}

void track_build(void)
{
    int k, e, h, n, sum, len, seg;
    /* the sections; the closing curve's curvature is what makes the lap's
       headings sum to 0 */
    e = 0;
    h = 0;
    sum = 0;
    for (k = 0; k < (int)NSECT - 1; k++) {
        if (k == CLOSING)
            break;
        h = section(e, sections[k], sections[k][3], 0, h);
        e += (sections[k][0] + sections[k][1] + sections[k][2]) * 8;
    }
    for (n = 0; n < e; n++)
        sum += trk_curve[n];
    {
        const short *s = sections[CLOSING];
        int enter = s[0] * 8, hold = s[1] * 8, leave = s[2] * 8;
        /* a ramp of r entries sums to about c * r / 2 */
        len = hold + (enter + leave) / 2;
        h = section(e, s, -(sum + len / 2) / len, 0, h);
        e += enter + hold + leave;
    }
    {
        short last[5] = {0, 0, 0, 0, 0};
        last[4] = -h;
        section(e, last, 0, TLEN - e, h);
    }
    /* what's left of the heading after rounding goes into the last entry */
    sum = 0;
    for (n = 0; n < TLEN; n++)
        sum += trk_curve[n];
    trk_curve[TLEN - 1] -= sum;
    /* the heading and the lateral position */
    {
        int a = 0, p = 0;
        for (n = 0; n <= TLEN; n++) {
            trk_head[n] = a;
            trk_pos[n] = p >> 12;
            p += a;
            a += trk_curve[n & TMASK];
        }
        drift = trk_pos[TLEN] - trk_pos[0];
    }
    for (k = 1; k <= NROWS; k++) {
        zt[k] = PROJ / k;
        kinfo[k] = (k - 1) << 8 | LK_ROAD;
    }
    zt[0] = zt[1];

    /* roadside objects: trees in rows, bushes, chevron signs before the
       curves on their outside */
    for (seg = 0; seg < NSEG; seg++) {
        SegObj *o = &seg_obj[seg];
        int c = trk_curve[((seg + 6) * 8) & TMASK], s;
        o->kind[0] = o->kind[1] = -1;
        if (c > 6 || c < -6) {
            if (seg % 4 == 0) {
                /* a right curve: the sign on the left, pointing right */
                o->kind[0] = c > 0 ? 3 : 2;
                o->x[0] = c > 0 ? -ROAD_W - 500 : ROAD_W + 500;
            }
            continue;
        }
        for (s = 0; s < 2; s++) {
            int side = s ? 1 : -1;
            if (seg % 4 == 2 * s && seg > 12) {
                o->kind[s] = 0;
                o->x[s] = side * (ROAD_W + 700 + rnd(900));
            } else if (rnd(5) == 0) {
                o->kind[s] = 1;
                o->x[s] = side * (ROAD_W + 450 + rnd(500));
            }
        }
    }
    /* the start: a gantry of signs either side */
    seg_obj[4].kind[0] = 4;
    seg_obj[4].x[0] = -ROAD_W - 300;
    seg_obj[4].kind[1] = 4;
    seg_obj[4].x[1] = ROAD_W + 300;

    /* the other cars: spread round the lap, in the lanes */
    for (k = 0; k < NCARS; k++) {
        cars[k].z = 6000 + k * 9000;
        cars[k].x = (k % 3 - 1) * (ROAD_W * 2 / 3);
        cars[k].speed = 60 + (k * 37) % 50;
        cars[k].kind = k & 1;
    }
}

/* the height and the curvature at world z */
int track_height_at(int z)
{
    return trk_height[(z >> TSHIFT) & TMASK];
}

int track_curve_at(int z)
{
    return trk_curve[(z >> TSHIFT) & TMASK];
}

/* the road's lateral position at an entry past the lap's end */
static int pos_at(int n)
{
    return n < TLEN ? trk_pos[n] : trk_pos[n - TLEN] + drift;
}

int proj_k, proj_q, proj_hcam;         /* the frame's constants, for the assembly too */

/* the per-frame constants: the camera's height, and Q and K of the screen
   x: sx = ((P - Q) * d) / 64 - K, P and Q in units of 16 */
static void proj_setup(void)
{
    int pz = camz + PROJ / D_CAR, np = pz >> TSHIFT, a = trk_head[np & TMASK];
    proj_hcam = track_height_at(camz + zt[NROWS]);   /* the nearest road at the screen's bottom */
    proj_q = pos_at(np) - ((a * ((PROJ / D_CAR) >> TSHIFT)) >> 12) + (px >> 4);
    proj_k = a >> 4;
}

void project(unsigned *desc)
{
    int d, y, ytop = NLINES, l;
    proj_setup();
#ifdef GFX_ASM
    ytop = project_asm(desc);
#else
    for (d = NROWS; d >= 6; d--) {
        int z = camz + zt[d], n = z >> TSHIFT, diff, sx, hh, stripe;
        unsigned w, info;
        diff = pos_at(n) - proj_q;
        if (diff > 32767)
            diff = 32767;
        if (diff < -32767)
            diff = -32767;
        sx = ((diff * d) >> 6) - proj_k;
        hh = CAM_H + proj_hcam - trk_height[n & TMASK];
        y = HY - 1 + ((d * hh) >> 10);
        stripe = (z >> 8) & 1;
        sx >>= XS;
        step_sx[d] = sx;
        step_yc[2 * d] = y;
        step_yc[2 * d + 1] = ytop;
        if (y >= ytop)
            continue;           /* behind a crest */
        if (y < HUD_LINES)
            y = HUD_LINES;
        w = soft ? 0 : road_desc(d - 1, sx, stripe);
        info = (unsigned)sx << 16 | (d - 1) << 8 | stripe << 4 | LK_ROAD;
        for (l = y; l < ytop; l++) {
            desc[l] = w;
            line_info[l] = info;
        }
        ytop = y;
    }
#endif
    road_top = ytop;
    /* between the road's end and the horizon: the grass beyond a crest */
    for (l = HY; l < ytop; l++) {
        desc[l] = grass_desc;
        line_info[l] = LK_GRASS;
    }
    for (l = HUD_LINES; l < ytop && l < HY; l++)
        line_info[l] = LK_BG;
    for (l = 0; l < HUD_LINES; l++)
        line_info[l] = LK_HUD;
}
