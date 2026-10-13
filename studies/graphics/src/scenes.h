/* The benchmark scenes, shared by the machine's main (main.c) and the
   host's (host.c). */

#ifndef SCENES_H
#define SCENES_H

#include "gfx.h"

#define SCREEN_W 640
#define SCREEN_H 480

/* The screen's memory, big enough for 640 x 480 at 8 bits per pixel. */
extern unsigned fb_mem[SCREEN_W * SCREEN_H / 4];

/* The end of a phase: the work since the previous mark is called name.
   Names starting with '_' are set-up, left out of the tables. On the
   machine this is a HALT, where the harness reads the cycles and the
   screen and resumes; on the host it prints the screen's checksum. */
void mark(const char *name);
void mark_n(const char *name, int count);    /* count: the work done, for rates */

/* Run a scene at a depth; returns 0, or -1 for an unknown scene. */
int run_scene(const char *name, int depth);

#endif
