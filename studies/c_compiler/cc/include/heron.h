#ifndef _HERON_H
#define _HERON_H
/* The machine's I/O page (studies/v1_isa/isa-v1.md). */
#define HERON_CONSOLE     (*(volatile unsigned *)0xFFFFFF00)  /* read: byte or -1; write: output */
#define HERON_CONSOLE_ST  (*(volatile unsigned *)0xFFFFFF04)  /* bit 0: byte waiting, bit 1: end */
#define HERON_TIMER       (*(volatile unsigned *)0xFFFFFF08)  /* period in cycles, 0 = off */
#define HERON_TIMER_FLAG  (*(volatile unsigned *)0xFFFFFF0C)  /* read: flag; write: acknowledge */
#define HERON_CYCLES      (*(volatile unsigned *)0xFFFFFF10)  /* cycle counter */
#endif
