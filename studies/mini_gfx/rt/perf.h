/* Timing with the beam (P1, video_ticks): master ticks of 19.86 ns, as
   "@perf" lines the harness collects (run.py). */

#ifndef PERF_H
#define PERF_H

/* a span: perf_end prints "@perf NAME TICKS" and returns the ticks since
   perf_start */
void perf_start(void);
unsigned perf_end(const char *name);
void perf_value(const char *name, unsigned v);

/* a game's frames: perf_frame_begin right after waiting for the frame,
   perf_frame_end before waiting again; perf_frames prints
   "@perf NAME AVG MAX N" (ticks of work a frame) */
void perf_frame_begin(void);
void perf_frame_end(void);
void perf_frames(const char *name);

#endif
