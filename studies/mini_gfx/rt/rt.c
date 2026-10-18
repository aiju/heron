/* The runtime: the interrupt's dispatch, and the marks the harness reads
   from the console (run.py). */

#include <stdio.h>
#include "mini.h"

volatile unsigned rt_frames;
void (*rt_frame_hook)(void);
void (*rt_line_hook)(int y);
void (*rt_video_irq)(void);
void (*rt_uart1_irq)(void);

void rt_init(void)
{
    rt_frames = 0;
    rt_ei();
}

void rt_irq(void)
{
    unsigned st = IRQ_STATUS;
    if ((st & 2) && rt_uart1_irq)
        rt_uart1_irq();
    if (st & 16) {
        if (rt_video_irq) {
            rt_video_irq();
        } else {
            VID_ACK = 0;
            rt_frames++;
        }
    }
}

void rt_mark(const char *what)
{
    printf("@mark %s %u\n", what, CYCLES);
}

void rt_shot(const char *name)
{
    unsigned f;
    printf("@shot %s\n", name);
    /* the harness saves the frame after the one this ends in */
    f = rt_frames;
    rt_wait_frame_after(f);
    rt_wait_frame_after(f + 1);
    rt_wait_frame_after(f + 2);
}
