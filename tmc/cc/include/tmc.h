#ifndef _TMC_H
#define _TMC_H
/* The machine's I/O page (docs/isa-v1.md). */
#define TMC_CONSOLE     (*(volatile unsigned *)0xFFFFFF00)  /* read: byte or -1; write: output */
#define TMC_CONSOLE_ST  (*(volatile unsigned *)0xFFFFFF04)  /* bit 0: byte waiting, bit 1: end */
#define TMC_TIMER       (*(volatile unsigned *)0xFFFFFF08)  /* period in cycles, 0 = off */
#define TMC_TIMER_FLAG  (*(volatile unsigned *)0xFFFFFF0C)  /* read: flag; write: acknowledge */
#define TMC_CYCLES      (*(volatile unsigned *)0xFFFFFF10)  /* cycle counter */
#endif
