/* The video (video.h). */

#include <string.h>
#include "video.h"

VideoInfo vid;
unsigned vid_palette[256];          /* what the palette was last written: it can't be read */
static int line_irqs;               /* descriptors with bit 23 set, so a video interrupt may be a line's */
static unsigned waited;             /* rt_frames at the last video_wait */
static char *vram_next;

extern void (*rt_video_irq)(void);

/* mode: picture width and height, bits a pixel, the XGA family */
static const short modes[7][4] = {
    {640, 480, 4, 0}, {320, 480, 8, 0}, {640, 480, 8, 0}, {640, 480, 2, 0},
    {640, 480, 1, 0}, {1024, 768, 2, 1}, {1024, 768, 1, 1},
};

/* the frame's end (frame_hook) or a descriptor's interrupt (line_hook):
   with line interrupts about, the beam (P1) tells which. A descriptor's
   interrupt for picture line y comes in line T + y, at character
   irq_char; the frame's in line 0. */
static void video_irq(void)
{
    unsigned b;
    int line, y;
    VID_ACK = 0;
    if (line_irqs) {
        b = VID_BEAM;
        line = b & 0x3FF;
        if (line >= vid.table) {
            y = line - vid.table;
            if ((int)((b >> 16) & 0xFF) < vid.irq_char)
                y--;            /* the handler started in the next line */
            if (rt_line_hook)
                rt_line_hook(y);
            return;
        }
    }
    rt_frames++;
    if (rt_frame_hook)
        rt_frame_hook();
}

void video_init(int mode, unsigned flags)
{
    int i;
    vid.mode = mode;
    vid.w = modes[mode][0];
    vid.h = modes[mode][1];
    vid.bpp = modes[mode][2];
    vid.xga = modes[mode][3];
    vid.words = vid.w * vid.bpp / 32;
    vid.lines = vid.xga ? 806 : 525;
    vid.table = vid.xga ? 37 : 44;
    vid.irq_char = vid.xga ? 134 : 85;
    vid.frame_ticks = vid.xga ? 839113 : 840000;
    if (!vram_next)
        vram_reset();
    line_irqs = 0;
    for (i = 0; i < 2048; i++)
        ((unsigned *)BANK1)[i] = 0;
    rt_video_irq = video_irq;
    vid.ctrl = VC_ON | VC_IRQ | VC_MODE(mode) | flags;
    VID_ACK = 0;
    VID_CTRL = vid.ctrl;
}

void video_ctrl(unsigned set, unsigned clear)
{
    vid.ctrl = (vid.ctrl & ~clear) | set;
    VID_CTRL = vid.ctrl;
}

unsigned *video_table(int t)
{
    return (unsigned *)BANK1 + 1024 * t + vid.table;
}

unsigned video_word(const void *p)
{
    return ((unsigned)p - BANK1) >> 2;
}

unsigned video_desc(const void *addr, int bank)
{
    return video_word(addr) | (unsigned)bank << 19;
}

void video_lines(int t, int y0, int n, const void *addr, int pitch, int bank)
{
    unsigned *d = video_table(t) + y0;
    unsigned w = video_desc(addr, bank), step = pitch >> 2;
    while (n-- > 0) {
        *d++ = w;
        w += step;
    }
}

void video_line_irq(int t, int y, int on)
{
    unsigned *d = video_table(t) + y;
    if (on) {
        *d |= 1 << 23;
        line_irqs++;
    } else {
        *d &= ~(1u << 23);
        line_irqs--;
    }
}

void video_show(int t)
{
    video_wait();
    video_ctrl(t ? VC_TSEL : 0, VC_TSEL);
}

void video_base(const void *addr, int bank)
{
    VID_FBASE = video_desc(addr, bank);
}

int video_wait(void)
{
    unsigned n;
    rt_wait_frame_after(waited);
    n = rt_frames - waited;
    waited = rt_frames;
    return n;
}

unsigned video_ticks(void)
{
    unsigned f, f2, b, st, line, pos;
    do {
        f = rt_frames;
        b = VID_BEAM;
        st = IRQ_STATUS;
        f2 = rt_frames;
    } while (f != f2);
    line = b & 0x3FF;
    if ((st & 16) && line < (unsigned)vid.table)
        f++;                    /* the frame has ended, its interrupt not taken yet */
    pos = line * (vid.xga ? 168 : 100) + ((b >> 16) & 0xFF);
    pos = vid.xga ? pos * 8056 / 1300 : pos * 16;
    return f * vid.frame_ticks + pos;
}

unsigned rgb565(int r, int g, int b)
{
    return (r >> 3) << 11 | (g >> 2) << 5 | b >> 3;
}

void video_pal(int n, unsigned c)
{
    vid_palette[n] = c;
    VID_PAL(n) = c;
}

void video_pal_rgb(int n, int r, int g, int b)
{
    video_pal(n, rgb565(r, g, b));
}

void video_pal_all(int n, unsigned c)
{
    int k;
    for (k = n; k < 256; k += 16)
        video_pal(k, c);
}

void video_cursor(const unsigned *image)
{
    VID_CURIMG = video_word(image);
    video_ctrl(VC_CURSOR, 0);
}

void video_cursor_at(int x, int y)
{
    VID_CURX = x & 0xFFF;
    VID_CURY = y & 0xFFF;
}

void vram_reset(void)
{
    vram_next = (char *)(BANK1 + 0x2000);
}

void *vram_alloc(unsigned bytes)
{
    char *p = vram_next;
    bytes = (bytes + 3) & ~3u;
    if ((unsigned)(p + bytes) > BANK1_END)
        return 0;
    vram_next = p + bytes;
    return p;
}
