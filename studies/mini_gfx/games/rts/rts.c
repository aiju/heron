/* A real-time strategy scene (rts.h has the plan): the set-up, the
   mouse and keys, the camera, and the benchmark.

   The pokes: mode (0: M0, 1: M1), strat (the redraw strategy, render.c),
   nunits (how many in the game), bench (1: the benchmark: units bouncing
   round the viewport, counts going up, "@perf" lines for each). */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rts.h"
#include "input.h"
#include "perf.h"

int mode = 0, bench = 0, strat = S_DOUBLE, nunits_start = 64, seed = 7;
int bpp, ppw, pshift, fmt, view_w, view_h, view_words, hud_h, rep, hud_base;
unsigned frame_no, t_logic, t_hud;
unsigned rng_state = 1;

#define CLEAN_BASE 0x100000     /* bank 0 above the heap's limit and below the stack */

unsigned rnd(void)
{
    rng_state = rng_state * 1103515245u + 12345u;
    return rng_state >> 16;
}

int rnd_n(int n) { return (int)((rnd() & 0x7FFF) % (unsigned)n); }

/* ---- the mode ---- */
static void setup_mode(void)
{
    int y;
    if (mode == 0) {
        video_init(0, VC_CURSOR);
        bpp = 4;
        view_w = 640;
        view_h = 400;
        hud_h = 80;
        rep = 1;
        hud_base = 0;
        map_w = 96;
        map_h = 64;
    } else {
        video_init(1, VC_CURSOR);
        bpp = 8;
        view_w = 320;
        view_h = 192;
        hud_h = 96;
        rep = 2;
        hud_base = 16;
        map_w = 64;
        map_h = 40;
    }
    ppw = 32 / bpp;
    pshift = bpp == 4 ? 3 : 2;
    fmt = gfx_screen_format();
    view_words = view_w / ppw;
    world_w = map_w * TILE;
    world_h = map_h * TILE;
    wpitch = world_w / ppw;
    wrowo = malloc(world_h * sizeof(int));
    for (y = 0; y < world_h; y++)
        wrowo[y] = y * wpitch;
    world[0] = vram_alloc(wpitch * 4 * world_h);
    world[1] = vram_alloc(wpitch * 4 * world_h);
    clean = (unsigned *)CLEAN_BASE;
    if (!world[1] || CLEAN_BASE + wpitch * 4 * world_h > 0x1C0000)
        printf("out of memory for the worlds\n");
}

/* ---- the camera: cam_x on a word (8 pixels in M0, 4 of M1's double-wide ones) ---- */
static void camera_clamp(void)
{
    if (cam_x > world_w - view_w)
        cam_x = world_w - view_w;
    if (cam_y > world_h - view_h)
        cam_y = world_h - view_h;
    if (cam_x < 0)
        cam_x = 0;
    if (cam_y < 0)
        cam_y = 0;
    cam_x &= ~(ppw - 1);
}

/* ---- the cursor: moved in the frame's interrupt, so it keeps up with
   the mouse at 60 Hz whatever the game's rate ---- */
static const unsigned *cursor_now;
static int cursor_hx, cursor_hy;

static void frame_hook(void)
{
    video_cursor_at(mouse_x - cursor_hx, mouse_y - cursor_hy);
}

static void cursor_set(const unsigned *img)
{
    if (img == cursor_now)
        return;
    cursor_now = img;
    cursor_hx = cursor_hy = img == cursor_target ? 15 : 0;
    VID_CURIMG = video_word(img);
}

/* ---- the mouse and the keys ---- */
static int drag, prev_buttons, scroll_keys;

static int in_view(int sy) { return sy < view_h * rep; }
static int world_x(int sx) { return cam_x + sx / rep; }
static int world_y(int sy) { return cam_y + sy / rep; }

static void input(void)
{
    Event e;
    while (input_next(&e)) {
        if (e.type == EV_KEY) {
            switch (e.ch) {
            case 's': units_stop(); break;
            case 'x': units_scatter(); break;
            case '+': units_spawn(32); break;
            case 'r': render_set((strategy + 1) % S_N); hud_buttons(); break;
            default:
                if (e.ch >= '1' && e.ch < '1' + S_N) {
                    render_set(e.ch - '1');
                    hud_buttons();
                }
                break;
            }
            continue;
        }
        if (e.type != EV_MOUSE)
            continue;
        {
            int pressed = e.buttons & ~prev_buttons, released = prev_buttons & ~e.buttons;
            prev_buttons = e.buttons;
            if ((pressed & 1) && in_view(e.y)) {
                drag = 1;
                sel_x0 = sel_x1 = world_x(e.x);
                sel_y0 = sel_y1 = world_y(e.y);
                sel_on = 1;
            } else if (pressed && !in_view(e.y)) {
                hud_click(e.x / rep, e.y - view_h * rep, pressed);
            } else if ((pressed & 2) && in_view(e.y)) {
                units_command(world_x(e.x), world_y(e.y));
            }
            if (drag) {
                sel_x1 = world_x(e.x);
                sel_y1 = world_y(e.y < view_h * rep ? e.y : view_h * rep - 1);
            }
            if ((released & 1) && drag) {
                int x0 = sel_x0 < sel_x1 ? sel_x0 : sel_x1, x1 = sel_x0 + sel_x1 - x0;
                int y0 = sel_y0 < sel_y1 ? sel_y0 : sel_y1, y1 = sel_y0 + sel_y1 - y0;
                units_select(x0, y0, x1 + 1, y1 + 1, 0);
                drag = 0;
                sel_on = 0;
                hud_info();
            }
        }
    }
}

/* the edge of the screen scrolls: a word (8 screen pixels) a frame */
static int edge_scroll(int dt)
{
    int dx = 0, dy = 0, ox = cam_x, oy = cam_y;
    if (mouse_x < 4)
        dx = -1;
    else if (mouse_x > 635)
        dx = 1;
    if (mouse_y < 4)
        dy = -1;
    else if (mouse_y > 475)
        dy = 1;
    if (dt > 4)
        dt = 4;
    cam_x += dx * ppw * dt;
    cam_y += dy * (8 / rep) * dt;
    camera_clamp();
    if (drag) {
        /* the drag's far corner follows the mouse over the scrolling world */
        sel_x1 = world_x(mouse_x);
        sel_y1 = world_y(mouse_y < view_h * rep ? mouse_y : view_h * rep - 1);
    }
    (void)scroll_keys;
    return cam_x != ox || cam_y != oy;
}

/* ---- timing ---- */
typedef struct {
    unsigned n, work, max, bg, erase, draw, logic, hud, items;
} Stats;
static Stats st;

static void stats_add(unsigned work)
{
    st.items += t_items;
    st.n++;
    st.work += work;
    if (work > st.max)
        st.max = work;
    st.bg += t_bg;
    st.erase += t_erase;
    st.draw += t_draw;
    st.logic += t_logic;
    st.hud += t_hud;
}

static void stats_print(const char *name)
{
    unsigned n = st.n ? st.n : 1;
    printf("@perf %s %u %u %u %u %u %u %u %u %u %u\n", name, st.work / n, st.max, st.n,
           st.bg / n, st.erase / n, st.draw / n, st.logic / n, st.hud / n, st.items / n, tears);
    memset(&st, 0, sizeof st);
}

/* ---- the game ---- */
static int tears_seen;          /* what the status line has shown */

static void status(unsigned work, int fps)
{
    char buf[48];
    if ((strategy == S_DIRTY || strategy == S_BEAM) && tears > tears_seen)
        sprintf(buf, "%u.%u ms, %d caught", work / 50352, work / 5035 % 10, tears - tears_seen);
    else
        sprintf(buf, mode ? "%d: %u.%u ms %d/s" : "%d units %u.%u ms %d fps", nunits,
                work / 50352, work / 5035 % 10, fps);
    tears_seen = tears;
    hud_status(buf);
}

static void game(void)
{
    unsigned t0, t1, t_wait, sum = 0, frames = 0, shown = 0;
    int dt = 1, f, last = strategy, last_n = nunits;
    char name[32];
    for (;;) {
        if (strategy != last || nunits != last_n) {
            /* the frames since the last change, for the harness */
            sprintf(name, "game_%s_%d", strategy_names[last], last_n);
            if (st.n)
                stats_print(name);
            tears = tears_seen = 0;
            last = strategy;
            last_n = nunits;
        }
        t0 = video_ticks();
        dt = render_frame();
        t1 = video_ticks();
        /* render_frame waited for the frame's end (and flipped); the rest is work */
        t_wait = t1 - t0 - t_draw - t_erase - t_bg;
        frame_no += dt;
        frames += dt;
        input();
        edge_scroll(dt);
        cursor_set(nsel && in_view(mouse_y) && !drag ? cursor_target : cursor_arrow);
        units_update(dt);
        field_step(200);
        t_logic = video_ticks() - t1;
        t1 = video_ticks();
        if ((frame_no & 7) < (unsigned)dt)
            hud_minimap();
        t_hud = video_ticks() - t1;
        sum += t_items + t_draw + t_erase + t_bg + t_logic + t_hud;
        stats_add(t_items + t_draw + t_erase + t_bg + t_logic + t_hud);
        shown++;
        if (frames >= 30) {
            status(sum / shown, shown * 60 / frames);
            sum = shown = frames = 0;
        }
        (void)t_wait;
        (void)f;
    }
}

/* ---- the kernels alone: ticks a call, the average of 64 ---- */
static void kernel_time(const char *name, int what, int n)
{
    /* into world 1's bottom rows (not shown by the benchmark's
       strategies but S_DOUBLE's other buffer), restored after */
    unsigned *d = world[1] + wrowo[world_h - 40] + 8, *s = clean + wrowo[world_h - 40] + 8;
    const Sprite *sp = &sprites[SPR_INDEX(1, 0, 0, 0, 0)];
    int k, ph = n == 2 ? 0 : n == 3 ? ppw - 1 : 1, tw = TILE / ppw;
    unsigned t = video_ticks();
    for (k = 0; k < 64; k++)
        switch (what) {
        case 0: k_copy(d, s, n, 12, wpitch * 4, wpitch * 4); break;
        case 1: k_sprite(d, sp->data[ph], sp->n[ph], sp->h, wpitch * 4); break;
        case 2: k_tile(d, tiles + T_TREE * tile_words, tw, wpitch * 4); break;
        }
    perf_value(name, (video_ticks() - t) / 64);
    k_copy(world[1] + wrowo[world_h - 40], clean + wrowo[world_h - 40], wpitch, 40, wpitch * 4,
           wpitch * 4);
}

static void kernels(void)
{
    unsigned *o = world[1] + wrowo[world_h - view_h], t;
    kernel_time("k_copy_2x12", 0, 2);
    kernel_time("k_copy_3x12", 0, 3);
    kernel_time("k_copy_4x12", 0, 4);
    kernel_time("k_sprite_2", 1, 2);
    kernel_time("k_sprite_3", 1, 3);
    if (ppw == 4)
        kernel_time("k_sprite_4", 1, 4);
    kernel_time("k_tile", 2, 0);
    /* a whole viewport's background, from the clean world */
    t = video_ticks();
    k_copy(o, clean, view_words, view_h, wpitch * 4, wpitch * 4);
    perf_value("k_view", video_ticks() - t);
    k_copy(o, clean + wrowo[world_h - view_h], wpitch, view_h, wpitch * 4, wpitch * 4);
}

/* ---- the benchmark: n units bouncing round the viewport, n going up ---- */
static const short counts[] = {0, 8, 16, 32, 48, 64, 96, 128, 160, 192, 256, 320, -1};

static void benchmark(void)
{
    int c, f;
    char name[32];
    cam_x = (world_w - view_w) / 2;
    cam_y = (world_h - view_h) / 2;
    camera_clamp();
    render_set(strat);
    hud_buttons();
    /* the cost of a scroll: the viewport's descriptors */
    perf_start();
    k_desc_c(video_table(0), video_word(world[0]), wpitch, view_h, rep);
    perf_end("desc");
    perf_start();
    hud_minimap();
    perf_end("minimap");
    kernels();
    for (c = 0; counts[c] >= 0 && counts[c] <= MAX_UNITS; c++) {
        units_init(counts[c], 1);
        render_frame();
        render_frame();
        tears = 0;
        memset(&st, 0, sizeof st);
        for (f = 0; f < 24; f++) {
            unsigned t1;
            int dt = render_frame();
            frame_no += dt;
            t1 = video_ticks();
            units_bench_update(1);
            t_logic = video_ticks() - t1;
            t1 = video_ticks();
            if ((frame_no & 7) == 0)
                hud_minimap();
            t_hud = video_ticks() - t1;
            stats_add(t_items + t_bg + t_erase + t_draw + t_logic + t_hud);
        }
        sprintf(name, "n%d", counts[c]);
        f = st.work / st.n > 4 * 840000;     /* slower than 15 frames a second: enough */
        stats_print(name);
        if (counts[c] == 64)
            rt_shot("bench64");
        if (f)
            break;
    }
    printf("@done\n");
}

int main(void)
{
    font_init();
    input_init();
    setup_mode();
    palette_init();
    rt_frame_hook = frame_hook;
    cursors_make();
    cursor_set(cursor_arrow);
    perf_start();
    tiles_make();
    sprites_make();
    perf_end("art");
    map_make(seed);
    perf_start();
    world_draw();
    perf_end("world");
    hud_init();
    render_init();
    cam_x = base_x[0] * TILE - view_w / 3;
    cam_y = base_y[0] * TILE - view_h / 3;
    camera_clamp();
    if (bench) {
        benchmark();
        return 0;
    }
    units_init(nunits_start, 0);
    render_set(strat);
    hud_buttons();
    hud_info();
    printf("@mark ready %u\n", frame_no);
    game();
    return 0;
}
