/* Vector drawing (vec.h): the buffers and their guard bands, the
   records, the four erase strategies and the C line kernel. */

#include <stdlib.h>
#include <string.h>
#include "vec.h"
#include "video.h"

Vec vec;

unsigned **vl_rows;
unsigned *vl_masks, *vl_mend;
int vl_ppwm1, vl_pshift, vl_pitchw, vl_pitchb, vl_half;

/* each colour's pixel masks (OR, XOR), and the inverted masks (clearing),
   each ppw words */
static unsigned *tab_col[16], *tab_clr;
static unsigned *row_mem[2];

static void set_masks(void)
{
    vl_masks = vec.op == VOP_CLR ? tab_clr : tab_col[vec.colour];
    vl_mend = vl_masks + vec.ppw;
}

void vec_select(int b)
{
    vec.back = b;
    vl_rows = vec.rows[b];
}

void vec_init(int mode, unsigned flags, int erase, int kernel, int guard)
{
    const Format *f;
    int b, y, i, c, rows, words;
    unsigned *fb;
    vram_reset();
    video_init(mode, flags);
    vec.mode = mode;
    vec.w = vid.w;
    vec.h = vid.h;
    vec.bpp = vid.bpp;
    vec.fmt = gfx_screen_format();
    f = gfx_format(vec.fmt);
    vec.pshift = f->pshift;
    vec.ppw = 1 << f->pshift;
    vec.vwords = vid.words;
    /* the guard band: whole words left and right, shared between a row's
       right and the next row's left (both are off the picture) */
    vec.gx = (guard + vec.ppw - 1) & ~(vec.ppw - 1);
    vec.gy = guard;
    vec.pitch = vec.vwords + vec.gx / vec.ppw;
    vec.erase = erase;
    vec.kernel = kernel;
    rows = vec.h + 2 * vec.gy;
    /* a word of slack each end for a line's last put */
    words = rows * vec.pitch + vec.gx / vec.ppw + 2;
    for (b = 0; b < 2; b++) {
        fb = vram_alloc(words * 4);
        memset(fb, 0, words * 4);
        fb += 1 + vec.gx / vec.ppw;
        vec.org[b] = fb + vec.gy * vec.pitch;
        if (!row_mem[b])
            row_mem[b] = malloc((768 + 2 * 128) * sizeof(unsigned *));
        vec.rows[b] = (unsigned **)row_mem[b] + vec.gy;
        for (y = -vec.gy; y < vec.h + vec.gy; y++)
            vec.rows[b][y] = vec.org[b] + y * vec.pitch;
        /* the library's view: the guard band's top left is (0, 0) */
        gfx_init(&vec.s[b], fb - vec.gx / vec.ppw, vec.w + 2 * vec.gx, rows, vec.pitch, vec.fmt);
        /* the picture's rows and the guard words between them, one row */
        gfx_init(&vec.flat[b], vec.org[b], vec.h * vec.pitch * vec.ppw, 1, vec.h * vec.pitch,
                 vec.fmt);
        video_lines(b, 0, vec.h, vec.org[b], vec.pitch * 4, 0);
        if (!vec.polys[b]) {
            vec.polys[b] = malloc(VEC_MAXP * sizeof(VPoly));
            vec.pool[b] = malloc(VEC_POOL * sizeof(short));
            vec.boxes[b] = malloc(VEC_MAXB * sizeof(Rect));
        }
        vec.npolys[b] = vec.npool[b] = vec.nboxes[b] = 0;
    }
    /* the mask tables */
    for (c = 0; c < 1 << vec.bpp; c++) {
        if (!tab_col[c])
            tab_col[c] = malloc(33 * sizeof(unsigned));
        for (i = 0; i < vec.ppw; i++)
            tab_col[c][i] = f->pmask[i] & gfx_solidf(f, c);
    }
    if (!tab_clr)
        tab_clr = malloc(33 * sizeof(unsigned));
    for (i = 0; i < vec.ppw; i++)
        tab_clr[i] = ~f->pmask[i];
    vl_ppwm1 = vec.ppw - 1;
    vl_pshift = vec.pshift;
    vl_pitchw = vec.pitch;
    vl_pitchb = vec.pitch * 4;
    vl_half = 0;
    vec.colour = (1 << vec.bpp) - 1;
    vec.op = erase == ER_XOR ? VOP_XOR : VOP_OR;
    set_masks();
#ifdef GFX_ASM
    vl_asm_setup(vec.pshift);
    vl_asm_op(vec.op);
#endif
    vec.recp = erase == ER_REDRAW || erase == ER_XOR;
    vec.recb = erase == ER_BOX || erase == ER_WBOX;
    vec_select(0);
    video_ctrl(0, VC_TSEL);
}

void vec_bank(int y0, int y1, int bank)
{
    int b, y;
    for (b = 0; b < 2; b++) {
        unsigned *d = video_table(b);
        for (y = y0; y < y1; y++)
            d[y] = (d[y] & ~(15u << 19)) | (unsigned)bank << 19;
    }
}

void vec_colour(int c)
{
    vec.colour = c & ((1 << vec.bpp) - 1);
    set_masks();
}

void vec_op(int op)
{
    if (op == vec.op)
        return;
    vec.op = op;
    set_masks();
#ifdef GFX_ASM
    vl_asm_op(op);
#endif
}

void vec_half(int on)
{
    vl_half = on;
}

/* ---- the kernels, chosen ---- */

static const unsigned char lib_rops[3] = {ROP_OR, ROP_XOR, ROP_AND};

void vec_kernel_line(int x0, int y0, int x1, int y1)
{
    switch (vec.kernel) {
    case VK_LIB:
        gfx_line(&vec.s[vec.back], x0 + vec.gx, y0 + vec.gy, x1 + vec.gx, y1 + vec.gy,
                 vec.op == VOP_CLR ? 0 : vec.colour, lib_rops[vec.op]);
        break;
#ifdef GFX_ASM
    case VK_ASM:
        vl_line_asm(x0, y0, x1, y1);
        break;
#endif
    default:
        if (vec.op == VOP_OR)
            vl_line_or_c(x0, y0, x1, y1);
        else if (vec.op == VOP_XOR)
            vl_line_xor_c(x0, y0, x1, y1);
        else
            vl_line_clr_c(x0, y0, x1, y1);
        break;
    }
}

void vec_kernel_poly(const short *p, int n, int ox, int oy, int closed)
{
    int i, x, y, x1, y1;
    void (*line)(int, int, int, int);
#ifdef GFX_ASM
    if (vec.kernel == VK_ASM) {
        vl_poly_asm(p, n, ox, oy, closed);
        return;
    }
#endif
    /* the C kernels without a choice a line; the library's through
       vec_kernel_line */
    line = vec.kernel == VK_LIB ? vec_kernel_line :
           vec.op == VOP_OR ? vl_line_or_c : vec.op == VOP_XOR ? vl_line_xor_c : vl_line_clr_c;
    x = p[0] + ox;
    y = p[1] + oy;
    for (i = 1; i < n; i++) {
        x1 = p[2 * i] + ox;
        y1 = p[2 * i + 1] + oy;
        line(x, y, x1, y1);
        x = x1;
        y = y1;
    }
    if (closed)
        line(x, y, p[0] + ox, p[1] + oy);
}

/* ---- drawing, recorded ---- */

static void record(const short *pts, int n, int ox, int oy, int closed, int copy)
{
    int b = vec.back;
    VPoly *r;
    if (vec.npolys[b] >= VEC_MAXP)
        return;
    if (copy) {
        short *d;
        int i;
        if (vec.npool[b] + 2 * n > VEC_POOL)
            return;
        d = vec.pool[b] + vec.npool[b];
        for (i = 0; i < 2 * n; i++)
            d[i] = pts[i];
        vec.npool[b] += 2 * n;
        pts = d;
    }
    r = &vec.polys[b][vec.npolys[b]++];
    r->pts = pts;
    r->ox = ox;
    r->oy = oy;
    r->n = n;
    r->closed = closed;
    r->c = vec.colour;
    r->half = vl_half;
}

void vec_poly(const short *pts, int n, int ox, int oy, int closed)
{
    if (vec.recp)
        record(pts, n, ox, oy, closed, 1);
    vec.drawn += closed ? n : n - 1;
    vec_kernel_poly(pts, n, ox, oy, closed);
}

void vec_spoly(const short *pts, int n, int ox, int oy, int closed)
{
    if (vec.recp)
        record(pts, n, ox, oy, closed, 0);
    vec.drawn += closed ? n : n - 1;
    vec_kernel_poly(pts, n, ox, oy, closed);
}

void vec_line(int x0, int y0, int x1, int y1)
{
    /* off the guard band: dropped (the game keeps its objects inside) */
    if ((unsigned)(x0 + vec.gx) >= (unsigned)(vec.w + 2 * vec.gx) ||
        (unsigned)(x1 + vec.gx) >= (unsigned)(vec.w + 2 * vec.gx) ||
        (unsigned)(y0 + vec.gy) >= (unsigned)(vec.h + 2 * vec.gy) ||
        (unsigned)(y1 + vec.gy) >= (unsigned)(vec.h + 2 * vec.gy))
        return;
    if (vec.recp) {
        short p[4];
        p[0] = x0;
        p[1] = y0;
        p[2] = x1;
        p[3] = y1;
        record(p, 2, 0, 0, 0, 1);
    }
    if (vec.recb) {
        if (x0 < vec.cur.x0) vec.cur.x0 = x0;
        if (x0 > vec.cur.x1) vec.cur.x1 = x0;
        if (x1 < vec.cur.x0) vec.cur.x0 = x1;
        if (x1 > vec.cur.x1) vec.cur.x1 = x1;
        if (y0 < vec.cur.y0) vec.cur.y0 = y0;
        if (y0 > vec.cur.y1) vec.cur.y1 = y0;
        if (y1 < vec.cur.y0) vec.cur.y0 = y1;
        if (y1 > vec.cur.y1) vec.cur.y1 = y1;
    }
    vec.drawn++;
    vec_kernel_line(x0, y0, x1, y1);
}

void vec_obj_begin(void)
{
    vec.cur.x0 = vec.cur.y0 = 0x7FFF;
    vec.cur.x1 = vec.cur.y1 = -0x7FFF;
}

void vec_obj_end(void)
{
    if (vec.cur.x1 >= vec.cur.x0)
        vec_box(vec.cur.x0, vec.cur.y0, vec.cur.x1, vec.cur.y1);
}

void vec_box(int x0, int y0, int x1, int y1)
{
    int b = vec.back;
    Rect *r;
    if (!vec.recb || vec.nboxes[b] >= VEC_MAXB)
        return;
    r = &vec.boxes[b][vec.nboxes[b]++];
    /* in the library surface's coordinates, half-open */
    r->x0 = x0 + vec.gx;
    r->y0 = y0 + vec.gy;
    r->x1 = x1 + vec.gx + 1;
    r->y1 = y1 + vec.gy + 1;
}

/* ---- erasing ---- */

/* a box widened to whole words, cleared by stores: no edge masks, so no
   reads; the whole frame is drawn again, so what else it clears doesn't
   matter */
void vec_clear_wbox(int b, const Rect *r)
{
    int w0 = (r->x0 - vec.gx) >> vec.pshift, w1 = (r->x1 - 1 - vec.gx) >> vec.pshift;
    int nw = w1 - w0 + 1, h = r->y1 - r->y0;
    unsigned *p = vec.rows[b][r->y0 - vec.gy] + w0;
#ifdef GFX_ASM
    while (nw > 16) {
        vl_clear_box_asm(p, 16, h, vl_pitchb);
        p += 16;
        nw -= 16;
    }
    vl_clear_box_asm(p, nw, h, vl_pitchb);
#else
    int pitch = vec.pitch, k;
    while (h-- > 0) {
        unsigned *q = p;
        for (k = nw; k > 0; k--)
            *q++ = 0;
        p += pitch;
    }
#endif
}

void vec_frame(void)
{
    int b = vec.back, i, op = vec.op, c = vec.colour, half = vl_half;
    unsigned t0 = video_ticks();
    switch (vec.erase) {
    case ER_FILL:
        gfx_fill(&vec.flat[b], 0, 0, vec.flat[b].w, 1, 0, ROP_COPY);
        break;
    case ER_REDRAW:
    case ER_XOR:
        vec_op(vec.erase == ER_XOR ? VOP_XOR : VOP_CLR);
        for (i = 0; i < vec.npolys[b]; i++) {
            const VPoly *r = &vec.polys[b][i];
            if (vec.erase == ER_XOR && r->c != vec.colour)
                vec_colour(r->c);
            vl_half = r->half;
            vec_kernel_poly(r->pts, r->n, r->ox, r->oy, r->closed);
        }
        vec_op(op);
        break;
    case ER_BOX:
        for (i = 0; i < vec.nboxes[b]; i++)
            gfx_fill_rect(&vec.s[b], &vec.boxes[b][i], 0, ROP_COPY);
        break;
    case ER_WBOX:
        for (i = 0; i < vec.nboxes[b]; i++)
            vec_clear_wbox(b, &vec.boxes[b][i]);
        break;
    }
    vec.npolys[b] = vec.npool[b] = vec.nboxes[b] = 0;
    vec_colour(c);
    vl_half = half;
    vec.drawn = 0;
    vec.t_erase = video_ticks() - t0;
}

int vec_show(void)
{
    int n = video_wait();
    video_ctrl(vec.back ? VC_TSEL : 0, VC_TSEL);
    vec_select(vec.back ^ 1);
    return n;
}

/* ---- the C kernel ----

   Mostly across (|dx| >= |dy|): left to right, a word's pixels at a
   time: the pixels' masks are ORed (ANDed, clearing) into acc, which goes
   into the word when the line steps to the next row or word. Mostly down:
   top to bottom, a pixel a row. Bresenham's error e starts at -d (d the
   major length) and a minor step comes when e + 2m >= 0, so step t's
   minor coordinate is floor((2 t m + d) / 2 d), as gfx_line's. With
   vl_half the line's last point (x1, y1) is left out, whichever end is
   drawn first, so a closed polyline drawn with XOR has every point once.

   PUT is what goes into a word: the three operations' kernels are the
   same code. */

#define VL_KERNEL(NAME, ACC0, ACC, PUT)                                         \
    void NAME(int x0, int y0, int x1, int y1)                                   \
    {                                                                           \
        int dx = x1 - x0, dy = y1 - y0, adx, ady, e, n, inc, dec, k, step;      \
        unsigned *p, acc, m;                                                    \
        const unsigned *t, *masks = vl_masks, *mend = vl_mend;                  \
        adx = dx < 0 ? -dx : dx;                                                \
        ady = dy < 0 ? -dy : dy;                                                \
        if (adx >= ady) {                                                       \
            int swapped = dx < 0;                                               \
            if (swapped) {                                                      \
                x0 = x1;                                                        \
                y0 = y1;                                                        \
                dy = -dy;                                                       \
            }                                                                   \
            step = dy < 0 ? -vl_pitchw : vl_pitchw;                             \
            e = -adx;                                                           \
            inc = 2 * ady;                                                      \
            dec = 2 * adx;                                                      \
            n = adx + 1;                                                        \
            if (vl_half) {                                                      \
                n--;                                                            \
                if (swapped) {                                                  \
                    e += inc;                                                   \
                    if (e >= 0) {                                               \
                        y0 += dy < 0 ? -1 : 1;                                  \
                        e -= dec;                                               \
                    }                                                           \
                    x0++;                                                       \
                }                                                               \
            }                                                                   \
            p = vl_rows[y0] + (x0 >> vl_pshift);                                \
            t = masks + (x0 & vl_ppwm1);                                        \
            while (n > 0) {                                                     \
                k = mend - t;                                                   \
                if (k > n)                                                      \
                    k = n;                                                      \
                n -= k;                                                         \
                acc = ACC0;                                                     \
                do {                                                            \
                    ACC(acc, *t);                                               \
                    t++;                                                        \
                    e += inc;                                                   \
                    if (e >= 0) {                                               \
                        PUT(p, acc);                                            \
                        acc = ACC0;                                             \
                        p += step;                                              \
                        e -= dec;                                               \
                    }                                                           \
                } while (--k);                                                  \
                PUT(p, acc);                                                    \
                p++;                                                            \
                t = masks;                                                      \
            }                                                                   \
        } else {                                                                \
            int swapped = dy < 0, sx;                                           \
            if (swapped) {                                                      \
                x0 = x1;                                                        \
                y0 = y1;                                                        \
                dx = -dx;                                                       \
            }                                                                   \
            sx = dx < 0 ? -1 : 1;                                               \
            e = -ady;                                                           \
            inc = 2 * adx;                                                      \
            dec = 2 * ady;                                                      \
            n = ady + 1;                                                        \
            if (vl_half) {                                                      \
                n--;                                                            \
                if (swapped) {                                                  \
                    e += inc;                                                   \
                    if (e >= 0) {                                               \
                        x0 += sx;                                               \
                        e -= dec;                                               \
                    }                                                           \
                    y0++;                                                       \
                }                                                               \
            }                                                                   \
            p = vl_rows[y0] + (x0 >> vl_pshift);                                \
            t = masks + (x0 & vl_ppwm1);                                        \
            m = *t;                                                             \
            step = vl_pitchw;                                                   \
            if (sx > 0) {                                                       \
                while (n-- > 0) {                                               \
                    PUT(p, m);                                                  \
                    p += step;                                                  \
                    e += inc;                                                   \
                    if (e >= 0) {                                               \
                        e -= dec;                                               \
                        if (++t == mend) {                                      \
                            t = masks;                                          \
                            p++;                                                \
                        }                                                       \
                        m = *t;                                                 \
                    }                                                           \
                }                                                               \
            } else {                                                            \
                while (n-- > 0) {                                               \
                    PUT(p, m);                                                  \
                    p += step;                                                  \
                    e += inc;                                                   \
                    if (e >= 0) {                                               \
                        e -= dec;                                               \
                        if (t == masks) {                                       \
                            t = mend;                                           \
                            p--;                                                \
                        }                                                       \
                        m = *--t;                                               \
                    }                                                           \
                }                                                               \
            }                                                                   \
        }                                                                       \
    }

#define ACC_OR(a, m) ((a) |= (m))
#define ACC_AND(a, m) ((a) &= (m))
#define PUT_OR(p, a) (*(p) |= (a))
#define PUT_XOR(p, a) (*(p) ^= (a))
#define PUT_AND(p, a) (*(p) &= (a))

VL_KERNEL(vl_line_or_c, 0, ACC_OR, PUT_OR)
VL_KERNEL(vl_line_xor_c, 0, ACC_OR, PUT_XOR)
/* clearing: the inverted masks, ANDed together */
VL_KERNEL(vl_line_clr_c, ~0u, ACC_AND, PUT_AND)

#ifdef GFX_ASM
/* ---- patching vline.s ----

   The sites are tables of code addresses (vline.s), 0 at the end. An
   operation is three opcode bytes: the gathering's start (MOV r0, #0 or
   #-1), the gathering (OR or AND r0, [r3]+) and the put (OR, XOR or AND
   rN, [r2]). Patched between lines, so no stale copy is in the prefetch
   queue. */
extern unsigned char *vl_site_init[], *vl_site_acc[], *vl_site_put[];
extern unsigned short *vl_site_shift[];

static int asm_op = -1;

void vl_asm_op(int op)
{
    static const unsigned char init[3] = {0x11, 0x11, 0x1D};
    static const unsigned char acc[3] = {0x96, 0x96, 0x86};
    static const unsigned char put[3] = {0x92, 0xA2, 0x82};
    int i;
    if (op == asm_op)
        return;
    asm_op = op;
    for (i = 0; vl_site_init[i]; i++)
        *vl_site_init[i] = init[op];
    for (i = 0; vl_site_acc[i]; i++)
        *vl_site_acc[i] = acc[op];
    for (i = 0; vl_site_put[i]; i++)
        *vl_site_put[i] = put[op];
}

/* ASR r0, #n: the opcode byte C8 + n's bit 0, the register byte r0 and
   n's bits 4-1 */
void vl_asm_setup(int pshift)
{
    int i, n = pshift - 2;
    for (i = 0; vl_site_shift[i]; i++)
        *vl_site_shift[i] = (0xC8 | (n & 1)) | (n >> 1) << 8;
    asm_op = -1;
}
#endif
