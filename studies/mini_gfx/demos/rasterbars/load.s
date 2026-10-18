; Work for the main program while the line interrupts come, to see what
; the CPU's instructions do to their latency (an interrupt is taken at an
; instruction's end, and the block instructions aren't interrupted), and
; the palette written as fast as the CPU can.
;
;   void load_alu(int n)                  n loops of short instructions
;   void load_div(int n)                  n divides (a microcoded loop)
;   void load_fill(unsigned *d, int n)    n FILLs of 256 words
;   void load_copy(unsigned *d, const unsigned *s, int n)   n COPYs of 256
;   void pal_mov(volatile unsigned *pal, const unsigned *c, int n)
;                                         n entries from c, a load and a store each
;   void pal_stm_n(volatile unsigned *pal, const unsigned *c, int n)
;                                         n times eight entries, LDM and STM
;   void pal_unrolled(volatile unsigned *pal, unsigned c, int n)
;                                         n times sixteen entries of c, a store each

        .global _load_alu, _load_div, _load_fill, _load_copy
        .global _pal_mov, _pal_stm_n, _pal_unrolled

        .section .text._load_alu
_load_alu:
        MOV  r2, #0
.l:     ADD  r2, r1
        XOR  r2, #5
        LSR  r2, #1
        DBNZ r1, .l
        RET

        .section .text._load_div
_load_div:
        MOV  r3, #7
.l:     MOV  r2, #100000
        DIVU r0:r2, r3
        DBNZ r1, .l
        RET

        .section .text._load_fill
_load_fill:
        MOV  r4, r2
        MOV  r5, r1
.l:     MOV  r1, r5
        MOV  r3, #256
        MOV  r0, #-1            ; the condition latch cleared (gfx/blk/blk.s)
        CLZ  r0, r0
        .half 0x01FD            ; FILL r3 words of r2 from r1
        DBNZ r4, .l
        RET

        .section .text._load_copy
_load_copy:
        MOV  r4, r3
        MOV  r5, r1
        MOV  r6, r2
.l:     MOV  r1, r5
        MOV  r2, r6
        MOV  r3, #256
        MOV  r0, #-1
        CLZ  r0, r0
        .half 0x02FD            ; COPY r3 words from r2 to r1
        DBNZ r4, .l
        RET

        .section .text._pal_mov
_pal_mov:
.l:     MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .l
        RET

        .section .text._pal_stm_n
_pal_stm_n:
        SAVE r7-r14
        MOV  r11, r1
        MOV  r12, r2
        MOV  r13, r3
.l:     LDM  r12, r3-r10
        STM  r11, r3-r10
        ADD  r11, #32
        ADD  r12, #32
        DBNZ r13, .l
        RESTORE r7-r14
        RET

        .section .text._pal_unrolled
_pal_unrolled:
.l:     MOV  [r1], r2
        MOV  [r1 + 4], r2
        MOV  [r1 + 8], r2
        MOV  [r1 + 12], r2
        MOV  [r1 + 16], r2
        MOV  [r1 + 20], r2
        MOV  [r1 + 24], r2
        MOV  [r1 + 28], r2
        MOV  [r1 + 32], r2
        MOV  [r1 + 36], r2
        MOV  [r1 + 40], r2
        MOV  [r1 + 44], r2
        MOV  [r1 + 48], r2
        MOV  [r1 + 52], r2
        MOV  [r1 + 56], r2
        MOV  [r1 + 60], r2
        DEC  r3
        BNE  .l
        RET

; unsigned poll_write(unsigned ch, unsigned colour): wait until the beam's
; character is ch or more (P1: bits 23-16), write palette entry 0, and
; return the beam just after: a palette change at a place within a line,
; as near as polling gets (the simulator shows only the line's start)
        .global _poll_write
        .section .text._poll_write
_poll_write:
.w:     MOV  r0, [0xF0000008]
        LSR  r0, #16
        ZXB  r0, r0
        CMP  r0, r1
        BLO  .w
        MOV  [0xF0000400], r2
        MOV  r1, [0xF0000008]
        RET
