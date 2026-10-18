; The plasma's and the fire's inner loops in draft 2 (plasma.c has the C
; ones and what they compute).
;
;   void plasma_row_asm(unsigned *d, const unsigned *a, const unsigned *b,
;                       unsigned c, int n)
;       n words (a multiple of 4): d[i] = a[i] + b[i] + c, four pixels a
;       word whose bytes never carry into each other (each term < 85)
;
;   void fire_rows_asm(unsigned *d, const unsigned *s, int rows, int words)
;       rows rows of `words` words: d's row r from s's rows r + 1 and r + 2
;       (s and d the same shape, s with two rows more below), each pixel
;       the average of its left, right, lower and second-lower neighbours
;       a row down, cooled by 1/8; four pixels a word, the averages by
;       halves without carries: (x & y) + ((x ^ y) >> 1 & 0x7F7F7F7F)

        .global _plasma_row_asm, _fire_rows_asm

        .section .text._plasma_row_asm
_plasma_row_asm:
        MOV  r5, [sp]           ; n
        LSR  r5, #2
.l:     MOV  r0, [r2]+
        ADD  r0, [r3]+
        ADD  r0, r4
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        ADD  r0, [r3]+
        ADD  r0, r4
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        ADD  r0, [r3]+
        ADD  r0, r4
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        ADD  r0, [r3]+
        ADD  r0, r4
        MOV  [r1]+, r0
        DEC  r5
        BNE  .l
        RET

; r1 d, r2 s, r3 rows, r4 words. In the loop: r5 the word to the left
; (wp), r6 this one (w), r7 the next (wn), r8 the second row's (dd), r9
; the second row's pointer, r10 0x7F7F7F7F, r11 0x1F1F1F1F, r12 the words
; left in the row, r13 rows left, r0 and r14 scratch, r2 the first row's
; pointer (on the next word)
        .section .text._fire_rows_asm
_fire_rows_asm:
        SAVE r7-r14
        MOV  r10, #0x7F7F7F7F
        MOV  r11, #0x1F1F1F1F
        MOV  r13, r3
.row:   LEA  r2, [r2 + r4*4]    ; the row below this one in s
        LEA  r9, [r2 + r4*4]    ; and the one below that
        MOV  r5, #0
        MOV  r6, [r2]+
        MOV  r12, r4
.word:  DEC  r12
        BEQ  .last
        MOV  r7, [r2]+          ; wn
        BRA  .go
.last:  MOV  r7, #0
.go:    MOV  r8, [r9]+          ; dd
        ; left: (w << 8) | (wp >> 24)
        MOV  r0, r6
        LSL  r0, #8
        LSR  r5, #24
        OR   r0, r5
        ; right: (w >> 8) | (wn << 24)
        MOV  r14, r7
        LSL  r14, #24
        MOV  r5, r6
        LSR  r5, #8
        OR   r14, r5
        ; a = avg(left, right) in r0
        MOV  r5, r0
        XOR  r5, r14
        LSR  r5, #1
        AND  r5, r10
        AND  r0, r14
        ADD  r0, r5
        ; b = avg(w, dd) in r8
        MOV  r5, r6
        XOR  r5, r8
        LSR  r5, #1
        AND  r5, r10
        AND  r8, r6
        ADD  r8, r5
        ; v = avg(a, b) in r0
        MOV  r5, r0
        XOR  r5, r8
        LSR  r5, #1
        AND  r5, r10
        AND  r0, r8
        ADD  r0, r5
        ; cooled: v - (v >> 3 & 0x1F1F1F1F)
        MOV  r5, r0
        LSR  r5, #3
        AND  r5, r11
        SUB  r0, r5
        MOV  [r1]+, r0
        MOV  r5, r6             ; wp <- w, w <- wn
        MOV  r6, r7
        TST  r12, r12
        BNE  .word
        ; s from the row after next back a row: the next row's first
        MOV  r0, r4
        LSL  r0, #2
        SUB  r2, r0
        DEC  r13
        BNE  .row
        RESTORE r7-r14
        RET

;   void plasma_row_l1_asm(unsigned *d, const unsigned *a, const unsigned *b,
;                          unsigned c, int n, const unsigned *t)
;       the same pixels for L1, where M1's pixel p has its bit i at 8i + 2p
;       (i < 4) or 8(i - 4) + 2p + 1: each byte through t (its bits where
;       pixel 0's go), shifted by 2p, the four ORed
        .global _plasma_row_l1_asm
        .section .text._plasma_row_l1_asm
_plasma_row_l1_asm:
        SAVE r8-r9
        MOV  r5, [sp + 8]       ; n
        MOV  r6, [sp + 12]      ; t
.l:     MOV  r0, [r2]+
        ADD  r0, [r3]+
        ADD  r0, r4
        ZXB  r8, r0
        MOV  r9, [r6 + r8*4]    ; pixel 0
        MOV  r8, r0
        LSR  r8, #8
        ZXB  r8, r8
        MOV  r8, [r6 + r8*4]
        LSL  r8, #2             ; pixel 1
        OR   r9, r8
        MOV  r8, r0
        LSR  r8, #16
        ZXB  r8, r8
        MOV  r8, [r6 + r8*4]
        LSL  r8, #4             ; pixel 2
        OR   r9, r8
        LSR  r0, #24
        MOV  r8, [r6 + r0*4]
        LSL  r8, #6             ; pixel 3
        OR   r9, r8
        MOV  [r1]+, r9
        DEC  r5
        BNE  .l
        RESTORE r8-r9
        RET
