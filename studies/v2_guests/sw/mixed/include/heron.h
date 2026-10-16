#ifndef _HERON_H
#define _HERON_H
/* A user process's I/O page under mixed.py's kernel: draft 1's console
   registers (RFC 0004), on a card of the process's own, mapped at
   0x00FFF000 in its address space. */
#define HERON_CONSOLE     (*(volatile unsigned *)0x00FFF000)  /* read: byte or -1; write: output */
#define HERON_CONSOLE_ST  (*(volatile unsigned *)0x00FFF004)  /* bit 0: byte waiting, bit 1: end */
#define HERON_TIMER       (*(volatile unsigned *)0x00FFF008)  /* period in cycles, 0 = off */
#define HERON_TIMER_FLAG  (*(volatile unsigned *)0x00FFF00C)  /* read: flag; write: acknowledge */
#define HERON_CYCLES      (*(volatile unsigned *)0x00FFF010)  /* cycle counter */
#endif
