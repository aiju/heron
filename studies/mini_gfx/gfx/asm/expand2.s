; _expand_wide(job): 1-bit expansion in draft 2 for the formats that
; aren't 8 pixels a word (expand.s has those, and its aligning pass and
; patch, used here too): 16 pixels a word (LIN2, CHK2, PL2: two bytes
; through two tables), 32 (LIN1: the bits are the mask; CHK1: four
; bytes through four tables), 4 (LIN8, PL8: a nibble through a table).
;
; One loop a kind, each word d ^= (d ^ t) & k with t = B ^ (m & A) and
; k = (m | K) & e: opaque A = fg ^ bg, B = bg, K = ~0; transparent A = 0,
; B = fg, K = 0; e the edge's mask (lmask, ~0, rmask).
;
; ExpandJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24, rmask 28,
; soff 32, fg 36, bg 40, opaque 44, f 48, fmt 52
; Format: pshift 4, lin 264, nx 268, xt 272
; The frame: [sp] the job, [sp + 4] pshift, [sp + 8] lin, [sp + 12] a byte

        .global _expand_wide
        .section .text._expand_wide
_expand_wide:
        MOV  r2, [r1 + 48]
        MOV  r3, [r2 + 4]       ; pshift
        MOV  r0, [r1 + 20]      ; n: the buffer (512 bytes) must hold n + 1 words' bits
        CMP  r3, #4
        BEQ  .p16
        CMP  r3, #5
        BEQ  .p32
        CMP  r3, #2
        BNE  .c
        CMP  r0, #900
        BLO  .go
        BRA  .c
.p16:   CMP  r0, #240
        BLO  .go
        BRA  .c
.p32:   CMP  r0, #120
        BLO  .go
.c:     JMP  _expand_rows_c

.go:    SAVE r7-r14
        SUB  sp, #16
        MOV  [sp], r1
        MOV  [sp + 4], r3
        MOV  r0, [r2 + 264]
        MOV  [sp + 8], r0
        BSR  _xpand_patch
        MOV  r12, [r1 + 16]     ; r12: rows
        MOV  r8, [r1]           ; r8: the destination row
        MOV  r9, [r1 + 4]       ; r9: the source row
.row:   MOV  r1, [sp]
        MOV  r2, r9
        MOV  r3, [r1 + 20]
        INC  r3                 ; n + 1 words
        MOV  r0, [sp + 4]
        CMP  r0, #4
        BNE  .b1
        LSL  r3, #1             ; 2 bytes a word
        BRA  .b3
.b1:    CMP  r0, #5
        BNE  .b2
        LSL  r3, #2             ; 4 bytes a word
        BRA  .b3
.b2:    INC  r3
        LSR  r3, #1             ; half a byte a word
.b3:    BSR  _xpand_align       ; r3: the row's bits, lined up
        MOV  r1, [sp]
        MOV  r2, r8             ; r2: the destination
        MOV  r4, [r1 + 20]      ; r4: words after this one
        MOV  r5, [r1 + 48]
        MOV  r5, [r5 + 272]     ; r5: the tables
        MOV  r13, [r1 + 24]     ; r13: e, lmask first
        MOVS r0, [r1 + 44]
        BEQ  .trans
        MOV  r6, [r1 + 36]
        MOV  r11, [r1 + 40]     ; r11: B = bg
        XOR  r6, r11            ; r6: A = fg ^ bg
        MOV  r10, #-1           ; r10: K
        BRA  .kind
.trans: MOV  r6, #0
        MOV  r11, [r1 + 36]     ; B = fg
        MOV  r10, #0
.kind:  MOV  r0, [sp + 4]
        CMP  r0, #4
        BEQ  .k16
        CMP  r0, #5
        BEQ  .k32
        BRA  .k4

; ---- 16 pixels a word: two bytes, tables 0 and 1
.k16:   MOVS r1, byte [r3]+
        MOV  r14, [r5 + r1*4]
        MOVS r1, byte [r3]+
        ADD  r1, #256
        MOV  r1, [r5 + r1*4]
        OR   r14, r1            ; m
        BSR  .apply
        BNE  .k16
        BRA  .next

; ---- 32 pixels a word: the bits themselves (LIN1), or four tables (CHK1)
.k32:   MOVS r0, [sp + 8]
        BNE  .k32l
.k32c:  MOV  r14, [r3]+
        MOV  r1, r14
        AND  r1, #255
        MOV  r0, [r5 + r1*4]
        LSR  r14, #8
        MOV  r1, r14
        AND  r1, #255
        ADD  r1, #256
        MOV  r1, [r5 + r1*4]
        OR   r0, r1
        LSR  r14, #8
        MOV  r1, r14
        AND  r1, #255
        ADD  r1, #512
        MOV  r1, [r5 + r1*4]
        OR   r0, r1
        LSR  r14, #8
        ADD  r14, #768
        MOV  r14, [r5 + r14*4]
        OR   r14, r0            ; m
        BSR  .apply
        BNE  .k32c
        BRA  .next
.k32l:  MOV  r14, [r3]+         ; m: the bits
        BSR  .apply
        BNE  .k32l
        BRA  .next

; ---- 4 pixels a word: a nibble, the low one first
.k4:    MOVS r0, byte [r3]+
        MOV  [sp + 12], r0
        AND  r0, #15
        MOV  r14, [r5 + r0*4]
        BSR  .apply
        BEQ  .next
        MOV  r0, [sp + 12]
        LSR  r0, #4
        MOV  r14, [r5 + r0*4]
        BSR  .apply
        BNE  .k4

.next:  MOV  r1, [sp]
        MOV  r0, [r1 + 8]
        LSL  r0, #2
        ADD  r8, r0
        MOV  r0, [r1 + 12]
        LSL  r0, #2
        ADD  r9, r0
        DEC  r12
        BNE  .row
        ADD  sp, #16
        RESTORE r7-r14
        RET

; a word: m in r14; d ^= (d ^ (B ^ (m & A))) & ((m | K) & e); then the
; next word's e; returns NE while words are left (r4 counts them down).
; Uses r0, r1, r14.
.apply: MOV  r0, r14
        AND  r0, r6
        XOR  r0, r11            ; t
        OR   r14, r10
        AND  r14, r13           ; k
        MOV  r1, [r2]
        XOR  r0, r1
        AND  r0, r14
        XOR  r1, r0
        MOV  [r2]+, r1
        MOV  r13, #-1
        MOVS r4, r4
        BEQ  .done
        DEC  r4
        BNE  .more
        MOV  r1, [sp]           ; the last word: rmask
        MOV  r13, [r1 + 28]
.more:  TST  r2, r2             ; NE: r2 is never 0
.done:  RET
