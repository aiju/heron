/* Racer: the program (NOTES.md has what it is and what it found).

   Options, poked by the harness (--poke NAME=V):
     mode_sel   0: M0 640 x 480 x 4 (palette banks), 1: M1 320 x 480 x 8
     soft       1: every road line rendered by the CPU each frame (by
                spans), for comparison; 0: the road from the descriptors
     prep_copy  1: a sprite's road lines copied from their source; 0:
                rendered by spans (dearer: nine spans' setup a line)
     sky_irq    1 (M0): the sky's gradient by line interrupts rewriting a
                palette entry every 4 lines; 0: by palette banks
     autopilot  1: the car steers itself when no steering key is down
     run_frames how many frames it races
     lookahead  how many segments ahead the roadside objects are drawn
     bench      1: time the kernels alone, and stop

   The frame loop: update the game by the frames since the last update,
   build the table not shown (descriptors, scratch lines, sprites, the
   HUD), and ask the frame interrupt to switch to it (TSEL), so a switch
   never comes mid-frame; then wait for the switch. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "racer.h"
#include "mini.h"
#include "input.h"
#include "perf.h"

int mode_sel = 0, soft = 0, prep_copy = 1, sky_irq = 0, autopilot = 1, run_frames = 1000;
int lookahead = 70, bench = 0;
/* screenshots at these frames of the race: a climb over the horizon, a
   crest with the road gone behind it, the S bends, a long climb */
static const short shot_at[4] = {130, 190, 305, 425};
static const char *shot_name[4] = {"climb", "crest", "bends", "hill"};

int W, PPW, PS, XS, NPH, M1;
const Format *F;
const unsigned *span_from;
int ppw_mask;
int camz, speed, px, steer_vis, lap = 1, lap_frames, best_frames, game_frames, shake;

#define MAXSPEED 150

/* ---- timing: each part's ticks, summed over the frames ---- */
static unsigned tsum[T_N], tlast;
static unsigned nbuilt, nshown;
static const char *tname[T_N] = {"logic", "project", "background", "place", "lines", "draw",
                                 "hud"};

void tmark(int part)
{
    unsigned t = video_ticks();
    tsum[part] += t - tlast;
    tlast = t;
}

/* ---- the switch between the tables, in the frame's interrupt ---- */
static volatile int flip_to = -1;

static void frame_hook(void)
{
    if (flip_to >= 0) {
        vid.ctrl = (vid.ctrl & ~VC_TSEL) | (flip_to ? VC_TSEL : 0);
        VID_CTRL = vid.ctrl;
        flip_to = -1;
    }
    if (sky_irq)
        sky_irq_frame();
}

/* ---- the game ---- */

static unsigned rs = 99;
static int rnd(int n)
{
    rs = rs * 1103515245 + 12345;
    return (rs >> 16) % n;
}

/* the nearest car ahead in a lane band around x: its distance, or a big number */
static int car_ahead(int x, int range, int *idx)
{
    int i, best = 1 << 30, pz = camz + PROJ / D_CAR;
    for (i = 0; i < NCARS; i++) {
        int dz = cars[i].z - pz, dx = cars[i].x - x;
        if (dz < -LAP / 2)
            dz += LAP;
        if (dz > LAP / 2)
            dz -= LAP;
        if (dz > -150 && dz < best && dx > -range && dx < range) {
            best = dz;
            if (idx)
                *idx = i;
        }
    }
    return best;
}

static void update(int dt)
{
    int f, i, left = key_down(K_LEFT), right = key_down(K_RIGHT);
    int gas = key_down(K_UP), brake = key_down(K_DOWN), steer = right - left;
    for (f = 0; f < dt; f++) {
        int pz = camz + PROJ / D_CAR, c = track_curve_at(pz), off, ci;
        /* the autopilot: keep to a lane, change lanes round a car ahead */
        if (autopilot && !left && !right) {
            static int lane = 1;
            int target = (lane - 1) * (ROAD_W * 2 / 3), ahead = car_ahead(target, 600, 0);
            if (ahead < 2600) {
                int l2;
                for (l2 = 0; l2 < 3; l2++)
                    if (car_ahead((l2 - 1) * (ROAD_W * 2 / 3), 600, 0) > 3000) {
                        lane = l2;
                        break;
                    }
                target = (lane - 1) * (ROAD_W * 2 / 3);
            }
            /* steer against the curve's pull, and toward the lane */
            steer = 0;
            if (px < target - 60 + c * speed / 40)
                steer = 1;
            else if (px > target + 60 + c * speed / 40)
                steer = -1;
            if (car_ahead(px, 500, &ci) < 900 && speed > cars[ci].speed)
                brake = 1;
            gas = !brake;
        }
        if (gas)
            speed += 2;
        else if (brake)
            speed -= 5;
        else
            speed -= 1;
        off = px > ROAD_W + 250 || px < -ROAD_W - 250;
        if (off && speed > 50)
            speed -= 4;
        if (speed > MAXSPEED)
            speed = MAXSPEED;
        if (speed < 0)
            speed = 0;
        shake = off && speed > 10 ? rnd(3) - 1 : 0;
        /* steering, and the curve pulling the car outward */
        px += steer * (speed * 5 / 16 + 4) * (speed > 0);
        px -= c * speed / 180;
        if (px > 2 * ROAD_W)
            px = 2 * ROAD_W;
        if (px < -2 * ROAD_W)
            px = -2 * ROAD_W;
        steer_vis = steer;
        /* the other cars; bumping one slows us to below its speed */
        for (i = 0; i < NCARS; i++) {
            int dz;
            cars[i].z += cars[i].speed;
            if (cars[i].z >= LAP)
                cars[i].z -= LAP;
            dz = cars[i].z - pz;
            if (dz < -LAP / 2)
                dz += LAP;
            if (dz > -60 && dz < 220 && px - cars[i].x < 700 && cars[i].x - px < 700 &&
                speed > cars[i].speed) {
                speed = cars[i].speed * 3 / 4;
                cars[i].z += 160;
            }
        }
        camz += speed;
        lap_frames++;
        if (camz >= LAP) {
            camz -= LAP;
            if (!best_frames || lap_frames < best_frames)
                best_frames = lap_frames;
            lap++;
            lap_frames = 0;
        }
        game_frames++;
    }
}

/* ---- the kernels alone (bench): "@perf bench.NAME TICKS" for n calls ---- */
static void run_bench(void)
{
    unsigned *desc = video_table(0), *line = pool[0] + 300 * SPITCH;
    int i;
    camz = 40000;
    px = 300;
    project(desc);
    perf_start();
    for (i = 0; i < 10; i++)
        project(desc);
    perf_end("bench.project_x10");
    perf_start();
    for (i = 0; i < 100; i++)
        copy_line(line, (const unsigned *)(BANK1 + ((desc[400] & 0x7FFFF) << 2)));
    perf_end("bench.copy_line_x100");
    perf_start();
    for (i = 0; i < 100; i++)
        road_line(line, 200, 30, 0);
    perf_end("bench.road_line_x100");
    perf_start();
    for (i = 0; i < 100; i++)
        scene_bg_desc(desc);
    perf_end("bench.bg_desc_x100");
    sprites_bench();
}

/* ---- a frame: table t ---- */
static void build(int t)
{
    unsigned *desc = video_table(t);
    project(desc);
    tmark(T_PROJ);
    scene_bg_desc(desc);
    /* the mountains turn with the road's heading; the clouds at half the rate */
    {
        extern int proj_k;
        bg_scroll[1] = (proj_k + 4096) << 8;
        bg_scroll[0] = (proj_k / 2 + 4096 + game_frames / 8) << 8;
    }
    tmark(T_BG);
    sprites_frame(desc, t);
    hud_draw(t, desc);
    tmark(T_HUD);
}

int main(void)
{
    int t = 0, k, shot = 0;
    unsigned last, f0;
    char name[24];
    input_init();
    font_init();
    M1 = mode_sel == 1;
    video_init(M1 ? 1 : 0, 0);
    video_ctrl(0, VC_ON);       /* dark while the scene is drawn */
    W = vid.w;
    PPW = 32 / vid.bpp;
    PS = M1 ? 2 : 3;
    XS = M1;
    NPH = PPW;
    F = gfx_format(gfx_screen_format());
    span_from = F->from;
    ppw_mask = PPW - 1;
    scene_palette();
    printf("racer: M%d, %s road, %s, sky by %s\n", M1, soft ? "software" : "descriptor",
           prep_copy ? "sprite lines copied" : "sprite lines rendered",
           M1 ? "64 lines" : sky_irq ? "line interrupts" : "palette banks");
    perf_start();
    track_build();
    perf_end("init.track");
    perf_start();
    scene_build();
    perf_end("init.scene");
    perf_start();
    sprites_build();
    perf_end("init.sprites");
    if (bench) {
        run_bench();
        printf("@done\n");
        return 0;
    }
    rt_frame_hook = frame_hook;
    if (sky_irq && !M1) {
        /* the runtime looks for line interrupts only once one is asked for */
        video_line_irq(0, 0, 1);
        rt_line_hook = sky_line_hook;
    }
    /* the first frame, then the picture on */
    build(1);
    video_show(1);
    video_ctrl(VC_ON, 0);
    t = 0;
    last = rt_frames;
    f0 = rt_frames;
    for (k = 0; k < T_N; k++)
        tsum[k] = 0;
    while (game_frames < run_frames) {
        int dt = rt_frames - last;
        last = rt_frames;
        if (dt < 1)
            dt = 1;
        nshown += dt;
        if (dt > 4)
            dt = 4;             /* the game slows down below 15 frames a second */
        perf_frame_begin();
        tlast = video_ticks();
        update(dt);
        tmark(T_LOGIC);
        build(t);
        perf_frame_end();
        nbuilt++;
        flip_to = t;
        while (flip_to >= 0)
            rt_wait_frame_after(rt_frames);
        t ^= 1;
        if (shot < 4 && game_frames >= shot_at[shot]) {
            sprintf(name, "%s%s", M1 ? "m1_" : soft ? "soft_" : sky_irq ? "irq_" : "",
                    shot_name[shot]);
            rt_shot(name);
            last = rt_frames;
            shot++;
        }
    }
    /* the measurements: a frame's work and its parts, averaged */
    perf_frames("frame");
    for (k = 0; k < T_N; k++) {
        sprintf(name, "part.%s", tname[k]);
        perf_value(name, tsum[k] / nbuilt);
    }
    /* counts, as plain lines (perf lines are shown as times) */
    printf("frames: %u built over %u shown, %u.%u a second\n", nbuilt, nshown,
           600 * nbuilt / nshown / 10, 600 * nbuilt / nshown % 10);
    printf("a frame: %u scratch lines, %u sprites, %u sprite words, %u line interrupts\n",
           spr_lines / nbuilt, spr_count / nbuilt, spr_words / nbuilt,
           sky_irqs / (rt_frames - f0));
    printf("lap %d at frame %d\n", lap, game_frames);
    printf("@done\n");
    return 0;
}
