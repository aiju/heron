/* The symbols (sch.h): each a list of lines, arcs and circles in units,
   pin 1 at the origin and every pin on a grid point; drawn on any surface
   at a zoom and a rotation (sym_draw), or once per zoom and rotation into
   a 1-bit sprite that the canvas expands in a colour (sym_sprite). And the
   labels' text: a 3 x 5 font of its own for small zooms, the library's
   sans12 for big ones, both put together as 1-bit bitmaps so a label is
   one expansion, not one per glyph. */

#include <stdlib.h>
#include <string.h>
#include "sch.h"
#include "video.h"

#define LN(x0, y0, x1, y1) {P_LINE, x0, y0, x1, y1, 0, 0, 0}
#define ARC(cx, cy, r, bx0, by0, bx1, by1) {P_ARC, cx, cy, r, bx0, by0, bx1, by1}
#define CIRC(cx, cy, r) {P_CIRC, cx, cy, r, 0, 0, 0, 0}
#define DISC(cx, cy, r) {P_DISC, cx, cy, r, 0, 0, 0, 0}
#define RECT(x0, y0, x1, y1) {P_RECT, x0, y0, x1, y1, 0, 0, 0}
/* a pin: its point, its number, and where the number goes (al: 0 none,
   1 starting there, 2 ending there) */
#define PIN(x, y, n, tx, ty, al) {P_PIN, x, y, n, tx, ty, al, 0}
#define END {P_END, 0, 0, 0, 0, 0, 0, 0}

/* a resistor, the zigzag: pins at 0 and 4 grid steps */
static const Prim p_res[] = {
    LN(0, 0, 4, 0), LN(4, 0, 5, -2), LN(5, -2, 7, 2), LN(7, 2, 9, -2), LN(9, -2, 11, 2),
    LN(11, 2, 12, 0), LN(12, 0, 16, 0), PIN(0, 0, 1, 0, 0, 0), PIN(16, 0, 2, 0, 0, 0), END,
};

/* a capacitor: two plates, pins 3 steps apart */
static const Prim p_cap[] = {
    LN(0, 0, 5, 0), LN(5, -3, 5, 3), LN(7, -3, 7, 3), LN(7, 0, 12, 0),
    PIN(0, 0, 1, 0, 0, 0), PIN(12, 0, 2, 0, 0, 0), END,
};

/* NAND: a D (the front a half circle) and a bubble; inputs at -1 and +1
   steps, the output 5 steps on */
static const Prim p_nand[] = {
    LN(0, -4, 4, -4), LN(0, 4, 4, 4), LN(4, -6, 4, 6), LN(4, -6, 10, -6), LN(4, 6, 10, 6),
    ARC(10, 0, 6, 10, -6, 16, 6), CIRC(17, 0, 1), LN(18, 0, 20, 0),
    PIN(0, -4, 1, 0, 0, 0), PIN(0, 4, 2, 0, 0, 0), PIN(20, 0, 3, 0, 0, 0), END,
};

/* NOR: a curved back (a circle of 10 about (-4, 0)), a pointed front (two
   arcs of 15 about (9, +-9)), a bubble; the output 6 steps on */
static const Prim p_nor[] = {
    ARC(-4, 0, 10, 4, -6, 6, 6), LN(0, -4, 5, -4), LN(0, 4, 5, 4), LN(4, -6, 9, -6),
    LN(4, 6, 9, 6), ARC(9, 9, 15, 9, -6, 21, 0), ARC(9, -9, 15, 9, 0, 21, 6), CIRC(22, 0, 1),
    LN(23, 0, 24, 0), PIN(0, -4, 1, 0, 0, 0), PIN(0, 4, 2, 0, 0, 0), PIN(24, 0, 3, 0, 0, 0),
    END,
};

/* an inverter: a triangle and a bubble */
static const Prim p_inv[] = {
    LN(0, 0, 4, 0), LN(4, -4, 4, 4), LN(4, -4, 12, 0), LN(4, 4, 12, 0), CIRC(13, 0, 1),
    LN(14, 0, 16, 0), PIN(0, 0, 1, 0, 0, 0), PIN(16, 0, 2, 0, 0, 0), END,
};

/* a DIP-14 package: a box with a notch, pins 1-7 down the left, 14-8 up
   the right, their numbers inside */
#define DIPL(k) LN(0, 4 * (k), 4, 4 * (k)), PIN(0, 4 * (k), (k) + 1, 6, 4 * (k), 1)
#define DIPR(k) LN(20, 4 * (k), 24, 4 * (k)), PIN(24, 4 * (k), 14 - (k), 18, 4 * (k), 2)
static const Prim p_dip14[] = {
    RECT(4, -3, 20, 27), ARC(12, -3, 2, 10, -3, 14, -1),
    DIPL(0), DIPL(1), DIPL(2), DIPL(3), DIPL(4), DIPL(5), DIPL(6),
    DIPR(0), DIPR(1), DIPR(2), DIPR(3), DIPR(4), DIPR(5), DIPR(6), END,
};

/* a two-pin connector: a box with two contacts, the pins to the right */
static const Prim p_conn[] = {
    RECT(-9, -3, -3, 7), CIRC(-6, 0, 1), CIRC(-6, 4, 1), LN(-5, 0, 0, 0), LN(-5, 4, 0, 4),
    PIN(0, 0, 1, 0, 0, 0), PIN(0, 4, 2, 0, 0, 0), END,
};

/* an LED: a diode (triangle and bar) and two arrows out of it */
static const Prim p_led[] = {
    LN(0, 0, 5, 0), LN(5, -3, 5, 3), LN(5, -3, 11, 0), LN(5, 3, 11, 0), LN(11, -3, 11, 3),
    LN(11, 0, 16, 0), LN(7, -4, 10, -7), LN(10, -7, 8, -7), LN(10, -7, 10, -5),
    LN(10, -4, 13, -7), LN(13, -7, 11, -7), LN(13, -7, 13, -5),
    PIN(0, 0, 1, 0, 0, 0), PIN(16, 0, 2, 0, 0, 0), END,
};

/* ground: three bars getting shorter */
static const Prim p_gnd[] = {
    LN(0, 0, 0, 4), LN(-4, 4, 4, 4), LN(-2, 6, 2, 6), LN(-1, 8, 1, 8), PIN(0, 0, 1, 0, 0, 0),
    END,
};

/* a supply: a bar on a stem */
static const Prim p_vcc[] = {
    LN(0, 0, 0, -4), LN(-3, -4, 3, -4), PIN(0, 0, 1, 0, 0, 0), END,
};

const Symbol symbols[T_N] = {
    {"Resistor", "R", "10k", p_res, LS_AUTO, "1|2"},
    {"Capacitor", "C", "100n", p_cap, LS_AUTO, "1|2"},
    {"NAND", "U", "74HC00", p_nand, LS_ABOVE, "A|B|Y"},
    {"NOR", "U", "74HC02", p_nor, LS_ABOVE, "A|B|Y"},
    {"Inverter", "U", "74HC04", p_inv, LS_ABOVE, "A|Y"},
    {"DIP-14", "U", "74HC00", p_dip14, LS_ABOVE, 0},
    {"Connector", "J", "CONN", p_conn, LS_AUTO, "1|2"},
    {"LED", "D", "LED", p_led, LS_AUTO, "A|K"},
    {"Ground", "#G", "GND", p_gnd, LS_NONE, "1"},
    {"Supply", "#P", "+5V", p_vcc, LS_VALUE_ABOVE, "1"},
};

signed char sym_box[T_N][4];

void rot_pt(int rot, int x, int y, int *rx, int *ry)
{
    switch (rot & 3) {
    case 0: *rx = x; *ry = y; break;
    case 1: *rx = -y; *ry = x; break;
    case 2: *rx = -x; *ry = -y; break;
    default: *rx = y; *ry = -x; break;
    }
}

/* units times a zoom of 1-4 without a multiply */
static int mz(int v, int z)
{
    switch (z) {
    case 1: return v;
    case 2: return v << 1;
    case 3: return (v << 1) + v;
    default: return v << 2;
    }
}

static void grow(signed char *b, int x0, int y0, int x1, int y1)
{
    if (x0 < b[0]) b[0] = x0;
    if (y0 < b[1]) b[1] = y0;
    if (x1 > b[2]) b[2] = x1;
    if (y1 > b[3]) b[3] = y1;
}

void symbols_init(void)
{
    int t;
    for (t = 0; t < T_N; t++) {
        const Prim *p;
        signed char *b = sym_box[t];
        b[0] = b[1] = 127;
        b[2] = b[3] = -128;
        for (p = symbols[t].prims; p->op != P_END; p++) {
            switch (p->op) {
            case P_LINE:
            case P_RECT:
                grow(b, p->a < p->c ? p->a : p->c, p->b < p->d ? p->b : p->d,
                     p->a > p->c ? p->a : p->c, p->b > p->d ? p->b : p->d);
                break;
            case P_ARC:
                grow(b, p->d, p->e, p->f, p->g);
                break;
            case P_CIRC:
            case P_DISC:
                grow(b, p->a - p->c, p->b - p->c, p->a + p->c, p->b + p->c);
                break;
            default:
                grow(b, p->a, p->b, p->a, p->b);
                break;
            }
        }
    }
}

/* an arc: the circle's pixels inside a box (inclusive), the midpoint way */
static void arc(Surface *s, int cx, int cy, int r, int bx0, int by0, int bx1, int by1,
                unsigned c, int rop)
{
    int x = r, y = 0, e = 1 - r, k;
    while (x >= y) {
        int px[8], py[8];
        px[0] = cx + x; py[0] = cy + y;
        px[1] = cx - x; py[1] = cy + y;
        px[2] = cx + x; py[2] = cy - y;
        px[3] = cx - x; py[3] = cy - y;
        px[4] = cx + y; py[4] = cy + x;
        px[5] = cx - y; py[5] = cy + x;
        px[6] = cx + y; py[6] = cy - x;
        px[7] = cx - y; py[7] = cy - x;
        for (k = 0; k < 8; k++)
            if (px[k] >= bx0 && px[k] <= bx1 && py[k] >= by0 && py[k] <= by1)
                gfx_pixel(s, px[k], py[k], c, rop);
        y++;
        if (e < 0) {
            e += 2 * y + 1;
        } else {
            x--;
            e += 2 * (y - x) + 1;
        }
    }
}

/* a line between two pixels: a fill when it's across or down */
static void line(Surface *s, int x0, int y0, int x1, int y1, unsigned c, int rop)
{
    if (y0 == y1)
        gfx_fill(s, x0 < x1 ? x0 : x1, y0, (x0 < x1 ? x1 : x0) + 1, y0 + 1, c, rop);
    else if (x0 == x1)
        sch_vline(s, x0, y0, y1, c, rop);
    else
        gfx_line(s, x0, y0, x1, y1, c, rop);
}

void sym_draw(Surface *s, int type, int rot, int px, int py, int z, unsigned c, int rop)
{
    const Prim *p;
    int x0, y0, x1, y1, t;
    char num[4];
    for (p = symbols[type].prims; p->op != P_END; p++) {
        switch (p->op) {
        case P_LINE:
            rot_pt(rot, p->a, p->b, &x0, &y0);
            rot_pt(rot, p->c, p->d, &x1, &y1);
            line(s, px + mz(x0, z), py + mz(y0, z), px + mz(x1, z), py + mz(y1, z), c, rop);
            break;
        case P_RECT:
            rot_pt(rot, p->a, p->b, &x0, &y0);
            rot_pt(rot, p->c, p->d, &x1, &y1);
            if (x0 > x1) { t = x0; x0 = x1; x1 = t; }
            if (y0 > y1) { t = y0; y0 = y1; y1 = t; }
            gfx_frame(s, px + mz(x0, z), py + mz(y0, z), px + mz(x1, z) + 1, py + mz(y1, z) + 1,
                      1, c, rop);
            break;
        case P_ARC:
            rot_pt(rot, p->a, p->b, &x0, &y0);
            {
                int bx0, by0, bx1, by1;
                rot_pt(rot, p->d, p->e, &bx0, &by0);
                rot_pt(rot, p->f, p->g, &bx1, &by1);
                if (bx0 > bx1) { t = bx0; bx0 = bx1; bx1 = t; }
                if (by0 > by1) { t = by0; by0 = by1; by1 = t; }
                arc(s, px + mz(x0, z), py + mz(y0, z), mz(p->c, z), px + mz(bx0, z),
                    py + mz(by0, z), px + mz(bx1, z), py + mz(by1, z), c, rop);
            }
            break;
        case P_CIRC:
            rot_pt(rot, p->a, p->b, &x0, &y0);
            gfx_circle(s, px + mz(x0, z), py + mz(y0, z), mz(p->c, z), c, rop);
            break;
        case P_DISC:
            rot_pt(rot, p->a, p->b, &x0, &y0);
            gfx_fill_circle(s, px + mz(x0, z), py + mz(y0, z), mz(p->c, z), c, rop);
            break;
        case P_PIN:
            /* the pin's number, upright, if it has one and the zoom shows it */
            if (p->f && z >= 2) {
                int w, tx, ty;
                num[0] = p->c >= 10 ? '0' + p->c / 10 : '0' + p->c;
                num[1] = p->c >= 10 ? '0' + p->c % 10 : 0;
                num[2] = 0;
                w = text_width(num, 0);
                rot_pt(rot, p->d, p->e, &tx, &ty);
                tx = px + mz(tx, z);
                ty = py + mz(ty, z) - 2;
                if ((rot & 1) == 0) {
                    int right = (p->f == 2) ^ (rot == 2);
                    if (right)
                        tx -= w;
                } else {
                    tx -= w / 2;
                    ty += rot == 1 ? 1 : -2;
                }
                text_draw(s, tx, ty, num, 0, c);
            }
            break;
        }
    }
}

/* ---- sprites ---- */

static Sprite cache[T_N][4];
unsigned sprite_ticks;

void sprite_make(Sprite *sp, int type, int rot, int z)
{
    const signed char *b = sym_box[type];
    int x0, y0, x1, y1, t;
    Surface s;
    unsigned t0 = ticks_now();
    rot_pt(rot, b[0], b[1], &x0, &y0);
    rot_pt(rot, b[2], b[3], &x1, &y1);
    if (x0 > x1) { t = x0; x0 = x1; x1 = t; }
    if (y0 > y1) { t = y0; y0 = y1; y1 = t; }
    /* a pixel's margin all round: circles of the zoom's rounding */
    sp->ox = 1 - mz(x0, z);
    sp->oy = 1 - mz(y0, z);
    sp->w = mz(x1 - x0, z) + 3;
    sp->h = mz(y1 - y0, z) + 3;
    /* a spare word a row: the expansion kernels read one past the end */
    sp->pitch = (sp->w + 31) / 32 + 1;
    sp->bits = calloc(sp->pitch * sp->h, 4);
    sp->zoom = z;
    gfx_init(&s, sp->bits, sp->w, sp->h, sp->pitch, PF_LIN1);
    sym_draw(&s, type, rot, sp->ox, sp->oy, z, 1, ROP_OR);
    sprite_ticks += ticks_now() - t0;
}

const Sprite *sym_sprite(int type, int rot, int z)
{
    Sprite *sp = &cache[type][rot & 3];
    if (sp->bits && sp->zoom != z) {
        free(sp->bits);
        sp->bits = 0;
    }
    if (!sp->bits)
        sprite_make(sp, type, rot & 3, z);
    return sp;
}

void sym_flush(void)
{
    int t, r;
    for (t = 0; t < T_N; t++)
        for (r = 0; r < 4; r++)
            if (cache[t][r].bits) {
                free(cache[t][r].bits);
                cache[t][r].bits = 0;
            }
}

/* ---- text ---- */

/* the 3 x 5 font, ' ' to 'z': five rows as octal digits, 4 the left pixel,
   2 the middle, 1 the right; 0 for a character it hasn't (drawn as its
   capital, or '?') */
static const char *const tiny[91] = {
    "00000", "22202", "55000", "57575", "36363", "51245", "25253", "22000",   /*  !"#$%&' */
    "12221", "42224", "05250", "02720", "00024", "00700", "00002", "11244",   /* ()*+,-./ */
    "75557", "26227", "71747", "71317", "55711", "74717", "74757", "71122",   /* 01234567 */
    "75757", "75717", "02020", "02024", "12421", "07070", "42124", "71302",   /* 89:;<=>? */
    "25745", "25755", "65656", "34443", "65556", "74647", "74644", "34553",   /* @ABCDEFG */
    "55755", "72227", "11152", "55655", "44447", "57755", "65555", "25552",   /* HIJKLMNO */
    "65644", "25563", "65655", "34216", "72222", "55557", "55552", "55775",   /* PQRSTUVW */
    "55255", "55222", "71247", "64446", "44211", "31113", "25000", "00007",   /* XYZ[\]^_ */
    "42000", 0, 0, 0, 0, 0, 0, 0,                                             /* `abcdefg */
    0, 0, 0, "44565", 0, "00775", "00655", 0,                                 /* hijklmno */
    "06564", 0, 0, 0, 0, "00557", 0, 0,                                       /* pqrstuvw */
    0, 0, 0,                                                                  /* xyz */
};

static const char *tiny_glyph(int c)
{
    if (c >= 'a' && c <= 'z' && !tiny[c - 32])
        c -= 32;
    if (c < 32 || c > 'z' || !tiny[c - 32])
        c = '?';
    return tiny[c - 32];
}

int text_width(const char *str, int big)
{
    int n = strlen(str);
    if (big)
        return font_width(font_sans, str);
    return n ? 4 * n - 1 : 0;
}

/* OR w bits (w < 32) into a row at bit x */
static void put_bits(unsigned *row, int x, unsigned v, int w)
{
    int o = x & 31;
    row[x >> 5] |= v << o;
    if (o + w > 32)
        row[(x >> 5) + 1] |= v >> (32 - o);
}

/* str's pixels into t (bits cleared first, t->pitch words a row) */
static void text_render(TextBm *t, const char *str, int big)
{
    int k, r, n = strlen(str);
    memset(t->bits, 0, t->pitch * t->h * 4);
    if (!big) {
        for (k = 0; k < n; k++) {
            const char *g = tiny_glyph((unsigned char)str[k]);
            for (r = 0; r < 5; r++) {
                int v = g[r] - '0';
                /* the octal digit's left pixel is its bit 2 */
                unsigned bits = (v >> 2 & 1) | (v & 2) | (v & 1) << 2;
                put_bits(t->bits + r * t->pitch, 4 * k, bits, 3);
            }
        }
        return;
    }
    {
        const Font *f = font_sans;
        int pen = 0;
        for (k = 0; k < n; k++) {
            int c = (unsigned char)str[k];
            const Glyph *g;
            if (c < f->first || c >= f->first + f->count)
                c = '?';
            g = &f->glyphs[c - f->first];
            for (r = 0; r < g->h; r++) {
                const unsigned *row = f->strike.bits + r * f->strike.pitch;
                int sx = g->sx, y = f->ascent + g->yoff + r;
                unsigned v = row[sx >> 5] >> (sx & 31);
                if ((sx & 31) + g->w > 32)
                    v |= row[(sx >> 5) + 1] << (32 - (sx & 31));
                v &= (1u << g->w) - 1;
                {
                    int x = pen + g->xoff;
                    if (x < 0) {
                        v >>= -x;
                        x = 0;
                    }
                    if (y >= 0 && y < t->h && g->w)
                        put_bits(t->bits + y * t->pitch, x, v, g->w);
                }
            }
            pen += g->adv;
        }
    }
}

static void text_size(TextBm *t, const char *str, int big)
{
    t->w = text_width(str, big);
    if (t->w < 1)
        t->w = 1;
    t->h = big ? font_sans->height : 5;
    t->pitch = (t->w + 31) / 32 + 1;
}

void text_make(TextBm *t, const char *str, int big)
{
    text_size(t, str, big);
    t->bits = malloc(t->pitch * t->h * 4);
    text_render(t, str, big);
}

void text_free(TextBm *t)
{
    free(t->bits);
    t->bits = 0;
}

/* a string once: through a buffer, one expansion */
void text_draw(Surface *s, int x, int y, const char *str, int big, unsigned c)
{
    static unsigned buf[16 * 24];
    TextBm t;
    Bitmap bm;
    text_size(&t, str, big);
    if (t.pitch * t.h > 16 * 24)
        return;
    t.bits = buf;
    text_render(&t, str, big);
    bm.bits = buf;
    bm.pitch = t.pitch;
    sch_expand(s, x, y, &bm, 0, 0, t.w, t.h, c, 0, XM_TRANS);
}
