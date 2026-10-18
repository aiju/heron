; The RTS's drawing kernels in draft 2 assembly (the asm and blk
; variants; kern.c has them in C). Words only: the sprites are
; pre-shifted, so any pixel format draws the same way. Each has its
; common widths unrolled (a row in one loop of at most 16 parcels, for
; DBNZ), and a general loop.

; void k_copy_asm(unsigned *d, const unsigned *s, int n, int h, int dpitch, int spitch)
;   h rows of n words from s to d; pitches in bytes
        .global _k_copy_asm
        .section .text._k_copy_asm
_k_copy_asm:
        CMP  r4, #0
        BLE  .ret
        CMP  r3, #0
        BLE  .ret
        MOV  r5, [sp]           ; r5, r6: from a row's end to the next row's start
        MOV  r6, [sp + 4]
        MOV  r0, r3
        LSL  r0, #2
        SUB  r5, r0
        SUB  r6, r0
        CMP  r3, #2
        BEQ  .n2
        CMP  r3, #3
        BEQ  .n3
        CMP  r3, #4
        BEQ  .n4
        BHI  .wide
.n1:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        ADD  r1, r5
        ADD  r2, r6
        DBNZ r4, .n1
.ret:   RET
; two and three words a row (LDM and STM took half as long again)
.n2:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        ADD  r1, r5
        ADD  r2, r6
        DBNZ r4, .n2
        RET
.n3:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        ADD  r1, r5
        ADD  r2, r6
        DBNZ r4, .n3
        RET
.n4:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        ADD  r1, r5
        ADD  r2, r6
        DBNZ r4, .n4
        RET
; four words a loop, then the rest
.wide:  SAVE r8-r9
.row:   MOV  r8, r3
        LSR  r8, #2
        MOV  r9, r3
        AND  r9, #3
.w4:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r8, .w4
        TST  r9, r9
        BEQ  .next
.w1:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r9, .w1
.next:  ADD  r1, r5
        ADD  r2, r6
        DEC  r4
        BNE  .row
        RESTORE r8-r9
        RET

; void k_sprite_asm(unsigned *d, const unsigned *s, int n, int h, int dpitch)
;   h rows of n (keep, image) pairs: d = (d & keep) | image
        .global _k_sprite_asm
        .section .text._k_sprite_asm
_k_sprite_asm:
        CMP  r4, #0
        BLE  .ret
        MOV  r5, [sp]
        MOV  r0, r3
        LSL  r0, #2
        SUB  r5, r0             ; r5: from a row's end to the next
        CMP  r3, #2
        BEQ  .n2
        CMP  r3, #3
        BEQ  .n3
        CMP  r3, #4
        BEQ  .n4
.g:     MOV  r6, r3
.gw:    MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r6, .gw
        ADD  r1, r5
        DBNZ r4, .g
.ret:   RET
.n2:    MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        ADD  r1, r5
        DBNZ r4, .n2
        RET
.n3:    MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        ADD  r1, r5
        DBNZ r4, .n3
        RET
.n4:    MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        ADD  r1, r5
        DEC  r4
        BNE  .n4
        RET

; void k_tile_asm(unsigned *d, const unsigned *s, int n, int dpitch)
;   16 rows of n words, one after the other from s (n is 2 in M0, 4 in M1)
        .global _k_tile_asm
        .section .text._k_tile_asm
_k_tile_asm:
        MOV  r0, r3
        LSL  r0, #2
        SUB  r4, r0             ; r4: from a row's end to the next
        MOV  r5, #16
        CMP  r3, #2
        BEQ  .t2
        CMP  r3, #4
        BEQ  .t4
.g:     MOV  r6, r3
.gw:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r6, .gw
        ADD  r1, r4
        DBNZ r5, .g
        RET
.t2:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        ADD  r1, r4
        DBNZ r5, .t2
        RET
.t4:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        ADD  r1, r4
        DBNZ r5, .t4
        RET
