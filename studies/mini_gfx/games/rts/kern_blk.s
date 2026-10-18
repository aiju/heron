; The RTS's kernels with the block instructions (the blk variant): COPY
; for rows of words (RFC 0041, 2.1). There's no block instruction for a
; masked sprite, so the blk variant draws its units with kern.s's
; k_sprite_asm. Before each block instruction, MOV rX, #-1 and CLZ clear
; the condition latch the microcode tests too early (the study's README).

; void k_copy_blk(unsigned *d, const unsigned *s, int n, int h, int dpitch, int spitch)
;   rows of 4 words or fewer go to k_copy_asm: COPY's setting up (and the
;   latch's clearing) costs more than it saves there (3 x 12 words: 1950
;   ticks with COPY, 1650 without)
        .global _k_copy_blk
        .section .text._k_copy_blk
_k_copy_blk:
        CMP  r3, #5
        BHS  .go
        JMP  _k_copy_asm
.go:    CMP  r4, #0
        BLE  .ret
        MOV  r5, [sp]
        MOV  r6, [sp + 4]
        MOV  r0, r3
        LSL  r0, #2
        SUB  r5, r0             ; COPY leaves r1 and r2 past the row
        SUB  r6, r0
.row:   MOV  r0, #-1
        CLZ  r0, r0
        .half 0x02FD            ; COPY: r3 words from r2 to r1
        ADD  r1, r5
        ADD  r2, r6
        DBNZ r4, .row
.ret:   RET

; void k_tile_blk(unsigned *d, const unsigned *s, int n, int dpitch)
;   16 rows of n words with COPY, a row each; rows of fewer than 8 words
;   (both modes' tiles: 2 words in M0, 4 in M1) go to k_tile_asm, COPY
;   being slower there (M1: 2990 ticks a tile with COPY, 2720 without)
        .global _k_tile_blk
        .section .text._k_tile_blk
_k_tile_blk:
        CMP  r3, #8
        BHS  .go
        JMP  _k_tile_asm
.go:    MOV  r0, r3
        LSL  r0, #2
        SUB  r4, r0
        MOV  r5, #16
.row:   MOV  r0, #-1
        CLZ  r0, r0
        .half 0x02FD            ; COPY
        ADD  r1, r4
        DBNZ r5, .row
        RET
