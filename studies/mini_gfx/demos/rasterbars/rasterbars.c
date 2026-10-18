/* Raster bars: coloured bars behind a logo, made by changing the palette
   as the beam goes down (RFC 0042: M0, 640 x 480 x 4, descriptors D0,
   the beam P1), in four ways, each measured:

     A  a line interrupt every line (a descriptor's bit 23) on a vector of
        its own (fast.s): palette entry 0 written in the 15 characters
        between the descriptor's read and the line's start
     B  the same through the runtime's C hook (rt_line_hook): too late, so
        each line gets its colour a line after it should (the simulator)
        or tears (the hardware)
     C  no interrupts: the 16 palette banks, one shade each, picked per
        line by the descriptors, rewritten each frame
     D  banks and interrupts together: line y in bank y mod 16, and an
        interrupt every 8 lines (C, through the runtime) writes the banks
        of the lines 8 to 15 below, which aren't on the screen: any colour
        on any line, two entries a line here, and a deadline 50 times as
        long

   Then A and D while the main program copies with COPY (an instruction
   that isn't interrupted); a tear map, which draws from the recorded
   times of the palette writes what the hardware would show (the
   simulator renders a line whole as it starts, so it can't tear); and
   fades done with the banks: 16 banks as 16 brightnesses, the
   descriptors picking one per line.

   It starts by measuring: the interrupt's latency on each path while the
   CPU halts, runs short instructions, divides, FILLs or COPYs, and how
   fast the palette can be written. */

#include <stdio.h>
#include <string.h>
#include "gfx.h"
#include "video.h"
#include "perf.h"
#include "fx.h"

/* fast.s */
void rb_fast(void);
void rb_probe(void);
void rb_probe_n(void);
void rb_probe_in(void);
unsigned *rb_base, *rb_ptr, rb_n, rb_y;
unsigned rb_beam_in[480], rb_beam_out[480];
unsigned *rb_beam_in_p = rb_beam_in, *rb_beam_out_p = rb_beam_out;

/* load.s */
void load_alu(int n);
void load_div(int n);
void load_fill(unsigned *d, int n);
void load_copy(unsigned *d, const unsigned *s, int n);
void pal_mov(volatile unsigned *pal, const unsigned *c, int n);
void pal_stm_n(volatile unsigned *pal, const unsigned *c, int n);
void pal_unrolled(volatile unsigned *pal, unsigned c, int n);
unsigned poll_write(unsigned ch, unsigned colour);

#define PAL ((volatile unsigned *)0xF0000400)
#define IRQ (1u << 23)

static Surface scr;
static unsigned *fb, *scratch;
static unsigned desc0;              /* line 0's descriptor, bank 0 */
static int t;                       /* the animation's clock, in frames */

/* ---------------------------------------------------------------- the picture */

/* the picture's 16 colours (every bank's 1-15; 0 is the bars) */
static const unsigned char pic[16][3] = {
    {0, 0, 0}, {20, 20, 40}, {40, 40, 80}, {60, 60, 120}, {90, 90, 160}, {120, 120, 200},
    {160, 160, 230}, {200, 200, 210}, {70, 70, 80}, {255, 200, 60}, {255, 120, 40},
    {220, 50, 40}, {60, 220, 90}, {60, 180, 255}, {140, 140, 150}, {255, 255, 255},
};

static void picture(void)
{
    int w;
    gfx_fill(&scr, 0, 0, 640, 480, 0, ROP_COPY);
    w = fx_logo_width("HERON", 14);
    fx_logo(&scr, (640 - w) / 2, 70, "HERON", 14, 3, 7, 15, 8);
    w = fx_logo_width("mini", 8);
    fx_logo(&scr, (640 - w) / 2, 270, "mini", 8, 2, 9, 15, 10);
}

static void label(const char *s)
{
    int n = strlen(s);
    gfx_fill(&scr, 0, 440, 640, 456, 0, ROP_COPY);
    font_cells(&scr, (640 - 8 * n) / 2 & ~7, 440, s, n, 15, -1);
}

/* the picture's colours 1-15 in every bank, at brightness level/15 */
static void picture_palette(int level)
{
    int b, n;
    for (b = 0; b < 16; b++)
        for (n = 1; n < 16; n++)
            video_pal(16 * b + n, fx_dim(pic[n][0], pic[n][1], pic[n][2], level));
}

/* every line from fb, bank `bank`, in both tables; irq: bit 23 on all */
static void lines(int bank, unsigned irq)
{
    int y, k;
    for (k = 0; k < 2; k++)
        for (y = 0; y < 480; y++)
            video_table(k)[y] = (desc0 + 80 * y) | bank << 19 | irq;
}

/* ---------------------------------------------------------------- the bars */

#define NBARS 7
#define BAR 40                      /* lines a bar */
static const unsigned char hue[NBARS][3] = {
    {255, 50, 50}, {255, 150, 0}, {240, 240, 0}, {40, 230, 60}, {0, 200, 255}, {70, 90, 255},
    {210, 70, 255},
};
static unsigned ramp[NBARS][BAR];   /* each bar's colour, line by line */
static unsigned sky[480];           /* the background's, a dark blue going lighter */
static unsigned rainbow[256];       /* the logo's face in D */
static unsigned cols[2][480 + 16];  /* a colour a line, this frame's and the next's */
static unsigned face[2][480 + 16];  /* D: the logo's face, a line */
static int front;                   /* cols[front] is on the screen */
static volatile int ready = -1;     /* the next frame's, when computed */

static int clamp255(int v)
{
    return v > 255 ? 255 : v;
}

static void bars_init(void)
{
    int i, k, l, w, a;
    for (i = 0; i < NBARS; i++)
        for (k = 0; k < BAR; k++) {
            l = fx_sin[k * 128 / BAR];          /* 0 .. 256 .. 0 */
            w = l > 160 ? (l - 160) * 2 : 0;    /* a white highlight in the middle */
            ramp[i][k] = rgb565(clamp255(hue[i][0] * l / 256 + w),
                                clamp255(hue[i][1] * l / 256 + w),
                                clamp255(hue[i][2] * l / 256 + w));
        }
    for (k = 0; k < 480; k++)
        sky[k] = rgb565(0, 0, 24 + k / 8);
    for (a = 0; a < 256; a++)
        rainbow[a] = rgb565(clamp255(128 + fx_sin[a] / 2), clamp255(128 + fx_sin[(a + 85) & 255] / 2),
                            clamp255(128 + fx_sin[(a + 170) & 255] / 2));
}

/* the bars' tops and depths at time t, back to front */
static int bar_y[NBARS], bar_order[NBARS];
static void bars_place(int n)
{
    int i, j, z[NBARS];
    for (i = 0; i < n; i++) {
        int a = (t * 3 + i * 256 / n) & 255;
        bar_y[i] = 240 - BAR / 2 + 190 * fx_sin[a] / 256;
        z[i] = fx_cos(a);
        bar_order[i] = i;
    }
    for (i = 1; i < n; i++)
        for (j = i; j > 0 && z[bar_order[j]] < z[bar_order[j - 1]]; j--) {
            int k = bar_order[j];
            bar_order[j] = bar_order[j - 1];
            bar_order[j - 1] = k;
        }
}

/* the next frame's colour a line: the sky, the bars over it back to front */
static void bars_compute(unsigned *c)
{
    int i, k, y, b;
    memcpy(c, sky, sizeof sky);
    bars_place(NBARS);
    for (i = 0; i < NBARS; i++) {
        b = bar_order[i];
        for (k = 0; k < BAR; k++) {
            y = bar_y[b] + k;
            if (y >= 0 && y < 480)
                c[y] = ramp[b][k];
        }
    }
}

/* D's too: the rainbow running down the logo's face */
static void face_compute(unsigned *c)
{
    int y, a = -t * 4;
    for (y = 0; y < 480; y++)
        c[y] = rainbow[(2 * y + a) & 255];
}

static void swap_hook(void)
{
    if (ready >= 0) {
        front = ready;
        ready = -1;
    }
    rb_base = cols[front] - vid.table;  /* the beam's line T + y: line y's colour */
}

/* ---------------------------------------------------------------- measuring */

static int units[8], nunits;

static void meter(int u)
{
    if (nunits < 8)
        units[nunits++] = u;
}

/* the share of the frame used, averaged over the frames metered */
static int used(void)
{
    int k, s = 0;
    for (k = 0; k < nunits; k++)
        s += units[k];
    s = nunits ? s / nunits : fx_idle_base;
    nunits = 0;
    return fx_used(s);
}

/* the share of the frame a part used (tenths of a percent, "@perf
   used_KEY"), and its per-frame computing alone (ticks, interrupts off) */
static void report(const char *key, const char *name, unsigned compute)
{
    int u = used(), c = compute / 840;
    char k[40];
    printf("%-40s %3d.%d%% of a frame, of which computing %d.%d%%, the rest %d.%d%%\n", name,
           u / 10, u % 10, c / 10, c % 10, (u - c) / 10, (u - c) % 10);
    sprintf(k, "used_%s", key);
    perf_value(k, u);
}

/* the main program's frame: the frame's work done, then wait (and meter
   the time left in the last 8 frames of a part), or COPY until the frame
   ends (work) */
static void frame_end(int f, int frames, int work, const char *shot)
{
    if (work) {
        unsigned fr = rt_frames;
        while (rt_frames == fr)
            load_copy(scratch, scratch + 1024, 1);
    } else if (f >= frames - 8)
        meter(fx_idle());
    else
        fx_idle();
    t++;
    if (f == frames - 12 && shot)
        rt_shot(shot);
}

/* fn alone, with interrupts off, from a frame's start: video_ticks counts
   a frame whose interrupt is pending only up to the picture's first line */
static unsigned timed_compute(void (*fn)(unsigned *), unsigned *c)
{
    unsigned tk;
    fx_idle();
    rt_di();
    tk = video_ticks();
    fn(c);
    tk = video_ticks() - tk;
    rt_ei();
    return tk;
}

/* ---------------------------------------------------------------- A: the fast vector */

/* frames of A; work: COPYs as the main program's work (interrupts held up) */
static void part_a(int frames, int work, const char *shot)
{
    int f;
    unsigned c = timed_compute(bars_compute, cols[!front]);
    rb_base = cols[front] - vid.table;
    rt_frame_hook = swap_hook;
    /* the vector first: the runtime would take a line's interrupt for the
       frame's (video_irq looks at the beam only with video_line_irq's) */
    fx_vector(rb_fast);
    lines(0, IRQ);
    for (f = 0; f < frames; f++) {
        bars_compute(cols[!front]);
        ready = !front;
        frame_end(f, frames, work, shot);
    }
    lines(0, 0);
    fx_vector_off();
    rt_frame_hook = 0;
    if (!work)
        report("A", "A fast vector, 1 write a line", c);
}

/* ---------------------------------------------------------------- B: the C hook */

static void hook_b(int y)
{
    PAL[0] = cols[front][y];
}

static void part_b(int frames, const char *shot)
{
    int f, y;
    unsigned c = timed_compute(bars_compute, cols[!front]);
    lines(0, 0);
    for (y = 0; y < 480; y++)
        video_line_irq(0, y, 1);
    rt_frame_hook = swap_hook;
    rt_line_hook = hook_b;
    for (f = 0; f < frames; f++) {
        bars_compute(cols[!front]);
        ready = !front;
        frame_end(f, frames, 0, shot);
    }
    for (y = 0; y < 480; y++)
        video_line_irq(0, y, 0);
    rt_line_hook = 0;
    rt_frame_hook = 0;
    report("B", "B C hook, 1 write a line", c);
}

/* ---------------------------------------------------------------- C: banks only */

/* three bars of five shades each in banks 1-15, bank 0 the black between;
   each table remembers its bars' lines, to put them back to bank 0 */
static const unsigned char shade[BAR / 4] = {1, 2, 3, 4, 5, 5, 4, 3, 2, 1};
static int c_old[2][3];
static int ctab;

static void banks_compute(unsigned *unused)
{
    int i, k, y, b;
    unsigned *d = video_table(ctab);
    (void)unused;
    for (i = 0; i < 3; i++)                 /* the old bars, two frames ago */
        for (k = 0, y = c_old[ctab][i]; k < BAR; k++, y++)
            if (y >= 0 && y < 480)
                d[y] = desc0 + 80 * y;
    bars_place(3);
    for (i = 0; i < 3; i++) {
        b = bar_order[i];
        y = bar_y[b];
        c_old[ctab][b] = y;
        for (k = 0; k < BAR; k++, y++)
            if (y >= 0 && y < 480)
                d[y] = (desc0 + 80 * y) | (unsigned)(1 + 5 * b + shade[k / 4] - 1) << 19;
    }
}

static void part_c(int frames, const char *shot)
{
    int f, b, s;
    unsigned c;
    lines(0, 0);
    for (b = 0; b < 3; b++)
        for (s = 1; s <= 5; s++)
            video_pal(16 * (1 + 5 * b + s - 1),
                      fx_dim(hue[2 * b][0], hue[2 * b][1], hue[2 * b][2], 3 * s));
    video_pal(0, 0);
    ctab = 1;
    c = timed_compute(banks_compute, 0);
    for (f = 0; f < frames; f++) {
        ctab ^= 1;                          /* the table not on the screen */
        banks_compute(0);
        frame_end(f, frames, 0, shot);
        video_ctrl(ctab ? VC_TSEL : 0, VC_TSEL);    /* in the blanking: the next frame's */
    }
    video_ctrl(0, VC_TSEL);
    lines(0, 0);
    report("C", "C banks, no interrupts", c);
}

/* ---------------------------------------------------------------- D: banks and interrupts */

/* line y is in bank y & 15; the interrupt of line 8k writes the colours
   of lines 8k + 8 .. 8k + 15, whose banks lines 8k - 8 .. 8k - 1 used and
   are done with. Two entries a line: the bars (0) and the logo's face (7),
   which gets a rainbow running down it. */
static void (*d_record)(int y0);

static void write_banks(int y0)
{
    const unsigned *c = cols[front] + y0, *fc = face[front] + y0;
    volatile unsigned *p = PAL + 16 * (y0 & 15);
    int k;
    for (k = 0; k < 8; k++) {
        p[0] = c[k];
        p[7] = fc[k];
        p += 16;
    }
    if (d_record)
        d_record(y0);
}

/* the k-th interrupt of the frame is line 8k's: counted, not taken from
   rt_line_hook's y, which the runtime works out from the beam and which
   is a line too far when the handler starts 100 characters or more late
   (a FILL or COPY under way) */
static int d_next;

static void hook_d(int y)
{
    (void)y;
    d_next += 8;
    if (d_next + 8 < 480)
        write_banks(d_next + 8);
}

static void frame_d(void)
{
    swap_hook();
    write_banks(0);
    write_banks(8);
    d_next = 0;
}

static void both_compute(unsigned *c)
{
    bars_compute(c);
    face_compute(c == cols[0] ? face[0] : face[1]);
}

static void part_d(int frames, int work, const char *shot)
{
    int f, y;
    unsigned c = timed_compute(both_compute, cols[!front]);
    for (y = 0; y < 480; y++)
        video_table(0)[y] = (desc0 + 80 * y) | (y & 15) << 19;
    for (y = 8; y < 480; y += 8)
        video_line_irq(0, y, 1);
    rt_frame_hook = frame_d;
    rt_line_hook = hook_d;
    for (f = 0; f < frames; f++) {
        both_compute(cols[!front]);
        ready = !front;
        frame_end(f, frames, work, shot);
    }
    for (y = 8; y < 480; y += 8)
        video_line_irq(0, y, 0);
    rt_line_hook = 0;
    rt_frame_hook = 0;
    lines(0, 0);
    picture_palette(15);
    if (!work)
        report("D", "D banks + C irq / 8 lines, 2 a line", c);
}

/* ---------------------------------------------------------------- the tear map */

/* A frame's palette writes, recorded as they happen: when (the beam just
   after the write), for which picture line, into which bank. tear() then
   works out, line by line, which of the line's pixels showed another
   line's colour: on the hardware the palette is read as each pixel goes
   out, so a write in the line's picture splits it there; the simulator
   renders the line whole at its start. */
#define NREC 1024
static unsigned rec_beam[NREC];
static short rec_line[NREC], rec_bank[NREC];
static volatile int nrec, recording;
static int rec_done;

static void record(unsigned beam, int line, int bank)
{
    if (recording && nrec < NREC) {
        rec_beam[nrec] = beam;
        rec_line[nrec] = line;
        rec_bank[nrec] = bank;
        nrec++;
    }
}

/* the beam in characters from the frame's start */
static int beam_chars(unsigned b)
{
    return (b & 0x3FF) * 100 + ((b >> 16) & 0xFF);
}

/* record the next whole frame (after the wait for its start) */
static void rec_frame_hook(void)
{
    if (recording) {
        recording = 0;
        rec_done = 1;
    } else if (!rec_done && nrec == 0)
        recording = 1;
}

static void hook_b_rec(int y)
{
    PAL[0] = cols[front][y];
    record(VID_BEAM, y, 0);
}

static void d_rec(int y0)
{
    unsigned b = VID_BEAM;
    int k;
    for (k = 0; k < 8; k++)
        record(b, y0 + k, (y0 + k) & 15);
}

/* the map: a panel 140 pixels wide for the line's 80 characters, each
   picture line a row: green where the line showed its own colour, yellow
   where its neighbour's (above or below), red where one further away;
   the counts of the lines the simulator shows wrong (the
   colour at the line's start) and of those the hardware would (any of
   its pixels). The records are in time order; each bank's are walked
   once, through nxt. */
static short nxt[NREC];

static void segment(int px, int x0, int x1, int y, int line)
{
    int off = line > y ? line - y : y - line;
    if (x1 > x0)
        gfx_fill(&scr, px + x0 * 7 / 4, y, px + x1 * 7 / 4, y + 1,
                 off == 0 ? 12 : off == 1 ? 9 : 11, ROP_COPY);
}

static void tear(int px, const char *name, int every_bank)
{
    int head[16], last[16], pos[16], cur[16];
    int y, i, b, s, c, x0, bad, n_torn = 0, n_wrong = 0, torn_px = 0;
    for (b = 0; b < 16; b++)
        head[b] = last[b] = cur[b] = -1;
    for (i = 0; i < nrec; i++) {
        b = rec_bank[i];
        nxt[i] = -1;
        if (last[b] >= 0)
            nxt[last[b]] = i;
        else
            head[b] = i;
        last[b] = i;
    }
    for (b = 0; b < 16; b++)
        pos[b] = head[b];
    for (y = 0; y < 480; y++) {
        b = every_bank ? y & 15 : 0;
        s = (vid.table + 1 + y) * 100;          /* the line's first character */
        while (pos[b] >= 0 && beam_chars(rec_beam[pos[b]]) <= s) {
            cur[b] = rec_line[pos[b]];          /* written before the line: from its start */
            pos[b] = nxt[pos[b]];
        }
        if (cur[b] != y)
            n_wrong++;
        x0 = 0;
        bad = 0;
        while (pos[b] >= 0 && (c = beam_chars(rec_beam[pos[b]]) - s) < 80) {
            segment(px, x0, c, y, cur[b]);
            if (cur[b] != y) {
                bad = 1;
                torn_px += 8 * (c - x0);
            }
            x0 = c;
            cur[b] = rec_line[pos[b]];
            pos[b] = nxt[pos[b]];
        }
        segment(px, x0, 80, y, cur[b]);
        if (cur[b] != y) {
            bad = 1;
            torn_px += 8 * (80 - x0);
        }
        n_torn += bad;
    }
    /* where the writes landed, from their line's first character */
    {
        int sum = 0, n = 0, mn = 9999, mx = -9999;
        for (i = 0; i < nrec; i++) {
            c = beam_chars(rec_beam[i]) - (vid.table + 1 + rec_line[i]) * 100;
            sum += c;
            n++;
            mn = c < mn ? c : mn;
            mx = c > mx ? c : mx;
        }
        printf("tear map %-10s writes from their line's start: min %d avg %d max %d characters\n",
               name, mn, n ? sum / n : 0, mx);
    }
    printf("tear map %-10s %3d lines wrong at their start (the simulator's view), %3d with pixels "
           "of another line's colour (the hardware's), %d.%d%% of the pixels\n", name, n_wrong,
           n_torn, torn_px / 3072, torn_px * 10 / 3072 % 10);
    font_cells(&scr, px + 70 - 4 * strlen(name), 456, name, strlen(name), 15, 0);
}

/* run `setup` for a frame with recording on, then draw its map */
static void capture(void (*setup)(int on), int work, int px, const char *name, int every_bank)
{
    int f;
    nrec = 0;
    rec_done = 0;
    recording = 0;
    setup(1);
    for (f = 0; f < 6 && !rec_done; f++) {
        bars_compute(cols[!front]);
        face_compute(face[!front]);
        ready = !front;
        frame_end(0, 100, work, 0);
    }
    setup(0);
    tear(px, name, every_bank);
}

/* the setups: A with rb_probe (its writes recorded in rb_beam_out, and
   the line each was for from the beam as it started, in rb_beam_in), B
   with the recording hook, D with write_banks recording */
static void chain_a(void)
{
    int i;
    swap_hook();
    if (recording) {                /* the frame just recorded: rb_probe's writes */
        for (i = 0; i < (int)rb_y && i < 480; i++)
            record(rb_beam_out[i], (rb_beam_in[i] & 0x3FF) - vid.table, 0);
    }
    rb_y = 0;
    rec_frame_hook();
}

static void setup_a(int on)
{
    if (on) {
        rb_y = 0;
        rt_frame_hook = chain_a;
        fx_vector(rb_probe);
        lines(0, IRQ);
    } else {
        lines(0, 0);
        fx_vector_off();
        rt_frame_hook = 0;
    }
}

static void chain_b(void)
{
    swap_hook();
    rec_frame_hook();
}

static void setup_b(int on)
{
    int y;
    for (y = 0; y < 480; y++)
        video_line_irq(0, y, on);
    rt_line_hook = on ? hook_b_rec : 0;
    rt_frame_hook = on ? chain_b : 0;
}

static void chain_d(void)
{
    rec_frame_hook();
    frame_d();
}

static void setup_d(int on)
{
    int y;
    for (y = 0; y < 480; y++)
        video_table(0)[y] = (desc0 + 80 * y) | (on ? (y & 15) << 19 : 0);
    for (y = 8; y < 480; y += 8)
        video_line_irq(0, y, on);
    rt_line_hook = on ? hook_d : 0;
    rt_frame_hook = on ? chain_d : 0;
    d_record = on ? d_rec : 0;
}

static void part_tears(const char *shot)
{
    gfx_fill(&scr, 0, 0, 640, 480, 0, ROP_COPY);
    video_pal(0, 0);
    capture(setup_a, 0, 16, "A idle", 0);
    capture(setup_b, 0, 172, "B C hook", 0);
    capture(setup_a, 1, 328, "A COPYing", 0);
    capture(setup_d, 1, 484, "D COPYing", 1);
    video_pal(0, 0);
    picture_palette(15);
    rt_shot(shot);
}

/* ---------------------------------------------------------------- fades */

/* 16 banks as 16 brightnesses of the picture's palette (a dark blue in
   colour 0 too); the descriptors pick one per line: a curtain coming
   down with a soft edge, then the whole picture fading out and in. */
static int fade_f;

static void fade_compute(unsigned *d)
{
    int y, l, f = fade_f;
    unsigned w = desc0;
    for (y = 0; y < 480; y++, w += 80) {
        if (f < 110)                        /* the curtain: level 15 above, 0 below */
            l = (f * 6 - y) >> 2;
        else                                /* out and back in */
            l = f < 155 ? 15 - (f - 110) / 3 : (f - 155) / 3;
        l = l < 0 ? 0 : l > 15 ? 15 : l;
        d[y] = w | l << 19;
    }
}

static void part_fade(const char *shot1, const char *shot2)
{
    int f, y, b, l, tab = 0;
    unsigned c;
    for (b = 0; b < 16; b++) {
        video_pal(16 * b, fx_dim(30, 30, 90, b));
        for (y = 1; y < 16; y++)
            video_pal(16 * b + y, fx_dim(pic[y][0], pic[y][1], pic[y][2], b));
    }
    fade_f = 100;
    c = timed_compute(fade_compute, video_table(1));
    for (f = 0; f < 200; f++) {
        tab ^= 1;
        fade_f = f;
        fade_compute(video_table(tab));
        if (f >= 100 && f < 108)
            meter(fx_idle());
        else
            fx_idle();
        video_ctrl(tab ? VC_TSEL : 0, VC_TSEL);
        if (f == 60 && shot1)
            rt_shot(shot1);
        if (f == 135 && shot2)
            rt_shot(shot2);
    }
    video_ctrl(0, VC_TSEL);
    report("fade_banks", "fade with banks (480 descriptors)", c);
    /* the same fade by writing the 15 colours each frame */
    lines(0, 0);
    for (f = 0; f < 32; f++) {
        l = f < 16 ? 15 - f : f - 16;
        if (f == 20)
            perf_start();
        for (y = 1; y < 16; y++)
            PAL[y] = fx_dim(pic[y][0], pic[y][1], pic[y][2], l);
        if (f == 20)
            c = perf_end("fade_palette");
        if (f >= 20 && f < 28)
            meter(fx_idle());
        else
            fx_idle();
    }
    report("fade_pal", "fade with 15 palette writes (fx_dim)", c);
}

/* ---------------------------------------------------------------- the probe */

static const char *loads[] = {"halt", "alu", "div", "fill", "copy"};
static unsigned list[512];
static unsigned c_beam[64];
static unsigned c_n;

static void probe_hook(int y)
{
    (void)y;
    if (c_n < 64)
        c_beam[c_n++] = VID_BEAM;
}

/* three frames of the main program doing `which`; the frame hook keeps
   the last one's records (from probe_rec, probe_n of them) */
static unsigned keep[64];
static int nkeep;
static volatile int want;
static const unsigned *probe_rec;
static volatile unsigned *probe_n;

static void probe_frame(void)
{
    if (want) {
        nkeep = *probe_n < 64 ? *probe_n : 64;
        memcpy(keep, probe_rec, 4 * nkeep);
        want = 0;
    }
    rb_y = 0;
    c_n = 0;
    rb_ptr = list;
}

static void run_load(int which, const unsigned *rec, volatile unsigned *n)
{
    unsigned f = rt_frames + 3;
    probe_rec = rec;
    probe_n = n;
    while (rt_frames < f) {
        if (rt_frames == f - 1)
            want = 1;
        switch (which) {
        case 0: rt_wait_frame_after(rt_frames); break;
        case 1: load_alu(200); break;
        case 2: load_div(50); break;
        case 3: load_fill(scratch, 4); break;
        case 4: load_copy(scratch, scratch + 512, 4); break;
        }
    }
}

/* the latency in characters of the interrupt of the lines every 8th,
   the latest before beam b: from its descriptor's read (line T + y,
   character 85) */
static int lat8(unsigned b)
{
    int c = beam_chars(b) - (vid.table * 100 + vid.irq_char);
    return c % 800;
}

static void stats(const char *path, const char *load)
{
    int i, mn = 99999, mx = -99999, sum = 0, l;
    char name[48];
    for (i = 0; i < nkeep; i++) {
        l = lat8(keep[i]);
        mn = l < mn ? l : mn;
        mx = l > mx ? l : mx;
        sum += l;
    }
    if (!nkeep)
        nkeep = 1;
    printf("latency %-11s %-5s min %3d avg %3d max %3d characters\n", path, load, mn, sum / nkeep,
           mx);
    sprintf(name, "lat_%s_%s", path, load);
    perf_value(name, mx);
    nkeep = 0;
}

static void probe(void)
{
    int y, k, n;
    unsigned tk;
    /* the runtime's C path: the beam as rt_line_hook starts */
    lines(0, 0);
    for (y = 0; y < 480; y += 8)
        video_line_irq(0, y, 1);
    rt_line_hook = probe_hook;
    rt_frame_hook = probe_frame;
    for (k = 0; k < 5; k++) {
        run_load(k, c_beam, &c_n);
        stats("c-hook", loads[k]);
    }
    rt_line_hook = 0;
    for (y = 0; y < 480; y += 8)
        video_line_irq(0, y, 0);
    /* the fast vector: the beam as it starts, and after its writes */
    lines(0, 0);
    rb_base = list - vid.table;
    fx_vector(rb_probe_in);
    for (y = 0; y < 480; y += 8)
        video_table(0)[y] |= IRQ;
    for (k = 0; k < 5; k++) {
        run_load(k, rb_beam_in, &rb_y);
        stats("asm-entry", loads[k]);
    }
    fx_vector(rb_probe);
    for (k = 0; k < 5; k++) {
        run_load(k, rb_beam_out, &rb_y);
        stats("asm-1write", loads[k]);
    }
    fx_vector(rb_probe_n);
    for (n = 1; n <= 16; n *= 2) {
        char name[16];
        rb_n = n;
        run_load(0, rb_beam_out, &rb_y);
        sprintf(name, "list-%dwrite", n);
        stats(name, "halt");
    }
    lines(0, 0);
    fx_vector_off();
    rt_frame_hook = 0;
    /* the palette as fast as it goes: 256 entries */
    rt_di();
    tk = video_ticks();
    pal_unrolled(PAL, 0, 16);
    tk = video_ticks() - tk;
    printf("palette: a store of a register    %2u ticks an entry\n", tk / 256);
    perf_value("pal_store", tk);
    tk = video_ticks();
    pal_mov(PAL, list, 256);
    tk = video_ticks() - tk;
    printf("palette: a load and a store, loop %2u ticks an entry\n", tk / 256);
    perf_value("pal_loop", tk);
    tk = video_ticks();
    pal_stm_n(PAL, list, 32);
    tk = video_ticks() - tk;
    printf("palette: LDM and STM of 8         %2u ticks an entry\n", tk / 256);
    perf_value("pal_ldm_stm", tk);
    tk = video_ticks();
    for (k = 0; k < 256; k++)
        PAL[k] = list[k];
    tk = video_ticks() - tk;
    printf("palette: C loop                   %2u ticks an entry\n", tk / 256);
    perf_value("pal_c", tk);
    /* within a line: poll the beam to character 40 (pixel 320), write;
       60 lines, where the writes landed */
    {
        int mn = 99, mx = 0, c;
        for (k = 0; k < 60; k++) {
            while ((VID_BEAM >> 16 & 0xFF) >= 40)
                ;                       /* the next line's first half */
            c = poll_write(40, 0) >> 16 & 0xFF;
            mn = c < mn ? c : mn;
            mx = c > mx ? c : mx;
        }
        printf("palette: polled to character 40, written by character %d to %d\n", mn, mx);
        perf_value("poll_min", mn);
        perf_value("poll_max", mx);
    }
    rt_ei();
}

/* ---------------------------------------------------------------- the repro */

#ifdef SWALLOW
/* the frame's interrupt swallowed by a line's acknowledge (-D SWALLOW=n):
   rb_noguard (n writes a line from a list, no beam read after its
   acknowledge) while the main program COPYs; the frames the runtime saw
   against the video's (counted from the beam going back to the top). A
   race: how many are lost depends on the phase of the COPYs */
void rb_noguard(void);

static void reset_list(void)
{
    rb_ptr = list;
}

static void swallow(void)
{
    unsigned f0 = rt_frames, polls = 0, video = 0, last = 0, b;
    rb_n = SWALLOW;
    rb_ptr = list;
    rt_frame_hook = reset_list;
    fx_vector(rb_noguard);
    lines(0, IRQ);
    while (video < 120) {
        load_copy(scratch, scratch + 1024, 1);
        b = VID_BEAM & 0x3FF;
        if (b < last)
            video++;                    /* the beam went back to the top */
        last = b;
        polls++;
    }
    lines(0, 0);
    fx_vector_off();
    rt_frame_hook = 0;
    printf("swallow: %u frames of the video, %u seen by the runtime\n", video, rt_frames - f0);
}
#endif

/* ---------------------------------------------------------------- main */

int main(void)
{
    fx_init();
    video_init(0, 0);
    fb = vram_alloc(80 * 4 * 480);
    scratch = vram_alloc(4096 * 4);
    desc0 = video_desc(fb, 0);
    gfx_screen(&scr, fb, 80);
    picture();
    picture_palette(15);
    video_pal(0, 0);
    lines(0, 0);
    bars_init();
#ifdef SWALLOW
    swallow();
#endif

    probe();
    picture_palette(15);
    fx_calibrate();
    printf("a frame: %d units of idle work\n", fx_idle_base);

    label("A: a line interrupt on its own vector, 1 palette write a line");
    part_a(100, 0, "a_fast");
    label("B: the line interrupt through the C hook: a line late");
    part_b(60, "b_chook");
    label("C: no interrupts, 15 palette banks of one shade each");
    part_c(80, "c_banks");
    label("D: 16 banks in turn, a C interrupt every 8 lines: 2 colours a line");
    part_d(100, 0, "d_rotate");
    label("A while the CPU COPYs: interrupts held up, bars torn");
    part_a(40, 1, "a_copy");
    label("D while the CPU COPYs: no harm, the deadline is 8 lines");
    part_d(40, 1, "d_copy");
    part_tears("tears");
    picture();
    label("fades: 16 banks as 16 brightnesses, a bank per line");
    part_fade("fade_curtain", "fade_out");
    printf("@done\n");
    return 0;
}
