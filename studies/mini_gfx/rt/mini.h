/* Heron Mini's devices as a C program sees them: RFC 0041's I/O space and
   RFC 0042's video registers, and the runtime around them (rt/). */

#ifndef MINI_H
#define MINI_H

#define REG(a) (*(volatile unsigned *)(a))

/* ---- the video (RFC 0042, 8) ---- */
#define VID_CTRL    REG(0xF0000000)     /* written */
#define VID_ACK     REG(0xF0000004)     /* written: the interrupt's acknowledge */
#define VID_BEAM    REG(0xF0000008)     /* read (P1): line in 9-0, character in 23-16 */
#define VID_FBASE   REG(0xF000000C)     /* written (D1) */
#define VID_CURX    REG(0xF0000010)     /* written (C1), signed 12 bits */
#define VID_CURY    REG(0xF0000014)
#define VID_CURIMG  REG(0xF0000018)     /* written (C1): a word address in bank 1 */
#define VID_PAL(n)  REG(0xF0000400 + 4 * (n))
#define IRQ_STATUS  REG(0xF0000800)     /* read: 0 UART 0, 1 UART 1, 4 the video, 7 the line */

/* the control register's bits */
#define VC_ON       0x001
#define VC_TSEL     0x002
#define VC_IRQ      0x004
#define VC_MODE(m)  ((m) << 4)
#define VC_F1       0x080
#define VC_CURSOR   0x100
#define VC_D1       0x200

/* ---- the UARTs (16C550), region 6 ---- */
#define UART0(r)    REG(0xE0000000 + 4 * (r))
#define UART1(r)    REG(0xE0000020 + 4 * (r))

/* ---- the simulations' test card (draft 1's I/O page) ---- */
#define CONSOLE     REG(0xFFFFFF00)
#define CYCLES      REG(0xFFFFFF10)

/* ---- the RAM ---- */
#define BANK1       0x00200000          /* the video's bank, 2 MB */
#define BANK1_END   0x00400000

/* ---- the runtime (rt.c, start.s) ---- */
void rt_init(void);
void rt_ei(void);
void rt_di(void);
/* wait (in HALT) until the frame count isn't `seen` any more */
void rt_wait_frame_after(unsigned seen);
extern volatile unsigned rt_frames;         /* frame interrupts so far */
extern void (*rt_frame_hook)(void);         /* called from the interrupt at each frame's end */
extern void (*rt_line_hook)(int y);         /* a descriptor's interrupt, for picture line y */

/* the simulations: a mark the harness (run.py) reads from the console */
void rt_mark(const char *what);
void rt_shot(const char *name);             /* a screenshot of the next frame */

#endif
