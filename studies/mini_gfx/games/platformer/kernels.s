; The platformer's inner loops in draft 2 (game.h declares them; kernels.c
; has them in C): copies of whole lines, shifted copies at 8 bits a pixel,
; masked sprites and the redraw of tile rows. The _blk ones use the mini's
; block instructions (RFC 0041, 2.1), each after MOV rX, #-1; CLZ rX, rX,
; which clears the condition latch the microcode tests first (gfx/blk/blk.s).
; Every routine is in its own section: a variant links only what it calls.

; ---- copies ----

; k_copy_asm(d, s, n): n words, a multiple of 4, four a loop
        .global _k_copy_asm
        .section .text._k_copy_asm
_k_copy_asm:
        LSR  r3, #2
        BEQ  .done
.l:     MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .l
.done:  RET

; k_copy_ldm(d, s, n): n words, a multiple of 8, with LDM and STM (for
; the measurements: their check of the register range costs cycles a
; register before the transfer starts). r4-r11 holds the link register,
; saved with the callee's.
        .global _k_copy_ldm
        .section .text._k_copy_ldm
_k_copy_ldm:
        SAVE r7-r11
        LSR  r3, #3
        BEQ  .done
.l:     LDM  r2, r4-r11
        STM  r1, r4-r11
        ADD  r2, #32
        ADD  r1, #32
        DBNZ r3, .l
.done:  RESTORE r7-r11
        RET

; k_copy_blk(d, s, n): COPY, n words (at most 256)
        .global _k_copy_blk
        .section .text._k_copy_blk
_k_copy_blk:
        MOV  r0, #-1
        CLZ  r0, r0
        .half 0x02FD            ; COPY
        RET

; k_fill_blk(d, v, n): FILL, n words (at most 256)
        .global _k_fill_blk
        .section .text._k_fill_blk
_k_fill_blk:
        MOV  r0, #-1
        CLZ  r0, r0
        .half 0x01FD            ; FILL
        RET

; ---- shifted copies: d[i] = s[i] >> 8p | s[i + 1] << 32 - 8p ----

; k_shift_asm(d, s, n, p): n even. Each source word is rotated right by 8p
; once (a rotation by 8 or 16 is one cycle, the result multiplexer's) and
; MERGEd with the one before under r0, the high 8p bits: rd = (rd & ~r0)
; | (rs & r0), so the rotated lo keeps its low bits and hi gives the rest.
        .global _k_shift_asm
        .section .text._k_shift_asm
_k_shift_asm:
        CMP  r4, #2
        BEQ  .p2
        BHI  .p3
        TST  r4, r4
        BNE  .p1
        JMP  _k_copy_asm
.p1:    MOV  r0, #0xFF000000
        MOV  r5, [r2]+
        ROR  r5, #8
        LSR  r3, #1
.l1:    MOV  r6, [r2]+
        ROR  r6, #8
        MERGE r5, r6, r0
        MOV  [r1]+, r5
        MOV  r5, [r2]+
        ROR  r5, #8
        MERGE r6, r5, r0
        MOV  [r1]+, r6
        DBNZ r3, .l1
        RET
.p2:    MOV  r0, #0xFFFF0000
        MOV  r5, [r2]+
        ROR  r5, #16
        LSR  r3, #1
.l2:    MOV  r6, [r2]+
        ROR  r6, #16
        MERGE r5, r6, r0
        MOV  [r1]+, r5
        MOV  r5, [r2]+
        ROR  r5, #16
        MERGE r6, r5, r0
        MOV  [r1]+, r6
        DBNZ r3, .l2
        RET
.p3:    MOV  r0, #0xFFFFFF00
        MOV  r5, [r2]+
        ROR  r5, #24
        LSR  r3, #1
.l3:    MOV  r6, [r2]+
        ROR  r6, #24
        MERGE r5, r6, r0
        MOV  [r1]+, r5
        MOV  r5, [r2]+
        ROR  r5, #24
        MERGE r6, r5, r0
        MOV  [r1]+, r6
        DBNZ r3, .l3
        RET

; k_shift_blk(d, s, n, p): BLIT 2p (a rotation by 8p bits), n at most 256.
; BLIT's lo (r5) is the first source word rotated; its mask (r0) the low
; 32 - 8p bits, which come from lo.
        .global _k_shift_blk
        .section .text._k_shift_blk
_k_shift_blk:
        TST  r4, r4
        BNE  .sh
        JMP  _k_copy_blk
.sh:    MOV  r5, [r2]+
        CMP  r4, #2
        BEQ  .b2
        BHI  .b3
        ROR  r5, #8
        MOV  r0, #0x00FFFFFF
        MOV  r6, #-1
        CLZ  r6, r6
        .half 0x12FD            ; BLIT 2
        RET
.b2:    ROR  r5, #16
        MOV  r0, #0x0000FFFF
        MOV  r6, #-1
        CLZ  r6, r6
        .half 0x14FD            ; BLIT 4
        RET
.b3:    ROR  r5, #24
        MOV  r0, #0x000000FF
        MOV  r6, #-1
        CLZ  r6, r6
        .half 0x16FD            ; BLIT 6
        RET

; ---- sprites ----

; k_sprite_asm(job): SprJob: rows 0, data 4, h 8, n 12, stride 16. Each
; word (d & keep) | image, keep and image read by the AND and the OR
; themselves: four memory accesses a word, a row of 5 or 4 words unrolled
; (the clipped ones a loop). No block instruction does this: BLIT's mask
; is one register for every word, not a second stream.
        .global _k_sprite_asm
        .section .text._k_sprite_asm
_k_sprite_asm:
        SAVE r8-r11
        MOV  r8, [r1]           ; r8: the rows' pointers
        MOV  r9, [r1 + 4]       ; r9: the data's row
        MOVS r10, [r1 + 8]      ; r10: rows left
        BLE  .done
        MOV  r11, [r1 + 16]
        LSL  r11, #2            ; r11: the stride in bytes
        MOV  r4, [r1 + 12]      ; r4: words a row
        CMP  r4, #5
        BEQ  .row5
        CMP  r4, #4
        BEQ  .row4
.row:   MOVS r3, [r8]+
        BEQ  .next
        MOV  r2, r9
        MOV  r5, r4
.w:     MOV  r1, [r3]
        AND  r1, [r2]+
        OR   r1, [r2]+
        MOV  [r3]+, r1
        DBNZ r5, .w
.next:  ADD  r9, r11
        DEC  r10
        BNE  .row
.done:  RESTORE r8-r11
        RET

.row5:  MOVS r3, [r8]+
        BEQ  .next5
        MOV  r2, r9
        MOV  r1, [r3]
        AND  r1, [r2]+
        OR   r1, [r2]+
        MOV  [r3]+, r1
        MOV  r1, [r3]
        AND  r1, [r2]+
        OR   r1, [r2]+
        MOV  [r3]+, r1
        MOV  r1, [r3]
        AND  r1, [r2]+
        OR   r1, [r2]+
        MOV  [r3]+, r1
        MOV  r1, [r3]
        AND  r1, [r2]+
        OR   r1, [r2]+
        MOV  [r3]+, r1
        MOV  r1, [r3]
        AND  r1, [r2]+
        OR   r1, [r2]+
        MOV  [r3], r1
.next5: ADD  r9, r11
        DEC  r10
        BNE  .row5
        RESTORE r8-r11
        RET

.row4:  MOVS r3, [r8]+
        BEQ  .next4
        MOV  r2, r9
        MOV  r1, [r3]
        AND  r1, [r2]+
        OR   r1, [r2]+
        MOV  [r3]+, r1
        MOV  r1, [r3]
        AND  r1, [r2]+
        OR   r1, [r2]+
        MOV  [r3]+, r1
        MOV  r1, [r3]
        AND  r1, [r2]+
        OR   r1, [r2]+
        MOV  [r3]+, r1
        MOV  r1, [r3]
        AND  r1, [r2]+
        OR   r1, [r2]+
        MOV  [r3], r1
.next4: ADD  r9, r11
        DEC  r10
        BNE  .row4
        RESTORE r8-r11
        RET

; k_sprite_save_asm(job): the same, each row's words stored at save (20)
; before they change: one more store a word. Every row is drawn.
        .global _k_sprite_save_asm
        .section .text._k_sprite_save_asm
_k_sprite_save_asm:
        SAVE r8-r11
        MOV  r8, [r1]           ; r8: the rows' pointers
        MOV  r9, [r1 + 4]       ; r9: the data's row
        MOVS r10, [r1 + 8]      ; r10: rows left
        BLE  .done
        MOV  r11, [r1 + 16]
        LSL  r11, #2            ; r11: the stride in bytes
        MOV  r4, [r1 + 12]      ; r4: words a row
        MOV  r6, [r1 + 20]      ; r6: where the old words go
.row:   MOV  r3, [r8]+
        MOV  r2, r9
        MOV  r5, r4
.w:     MOV  r1, [r3]
        MOV  [r6]+, r1
        AND  r1, [r2]+
        OR   r1, [r2]+
        MOV  [r3]+, r1
        DBNZ r5, .w
        ADD  r9, r11
        DEC  r10
        BNE  .row
.done:  RESTORE r8-r11
        RET

; k_restore_asm(job): what k_sprite_save_asm kept put back: each row's n
; words from save, in order
        .global _k_restore_asm
        .section .text._k_restore_asm
_k_restore_asm:
        SAVE r8-r9
        MOV  r8, [r1]           ; r8: the rows' pointers
        MOVS r9, [r1 + 8]       ; r9: rows left
        BLE  .done
        MOV  r4, [r1 + 12]      ; r4: words a row
        MOV  r2, [r1 + 20]      ; r2: the kept words
.row:   MOV  r3, [r8]+
        MOV  r5, r4
.w:     MOV  r0, [r2]+
        MOV  [r3]+, r0
        DBNZ r5, .w
        DEC  r9
        BNE  .row
.done:  RESTORE r8-r9
        RET

; ---- descriptors ----

; k_desc_asm(d, src, n): n lines' descriptors, each twice (M1's lines
; doubled): the word address in bank 1 of src[i], palette bank 0
        .global _k_desc_asm
        .section .text._k_desc_asm
_k_desc_asm:
        MOV  r4, #0x200000
.l:     MOV  r0, [r2]+
        SUB  r0, r4
        LSR  r0, #2
        MOV  [r1]+, r0
        MOV  [r1]+, r0
        DBNZ r3, .l
        RET

; ---- the full redraw ----

; k_redraw_asm(job): RedrawJob: d 0, pitch 4, h 8, tiles 12. For each
; line: the first tile's words 1-3, then for 20 tiles the word before
; finished with the tile's word 0 and its words 1-3, then the 22nd tile's
; word 0 into the last. r10 steps through the tiles' lines (20 bytes).
        .global _k_redraw_asm
        .section .text._k_redraw_asm
_k_redraw_asm:
        SAVE r8-r14
        MOV  r8, [r1]           ; r8: the line
        MOV  r9, [r1 + 4]
        LSL  r9, #2             ; r9: the pitch in bytes
        MOV  r12, [r1 + 8]      ; r12: lines left
        MOV  r11, [r1 + 12]     ; r11: the tiles
        MOV  r10, #0            ; r10: the line in a tile's image
.line:  MOV  r3, r8
        MOV  r2, r11
        MOV  r6, [r2]+
        ADD  r6, r10
        MOV  r4, [r6 + 4]
        MOV  [r3]+, r4
        MOV  r4, [r6 + 8]
        MOV  [r3]+, r4
        MOV  r4, [r6 + 12]
        MOV  [r3]+, r4
        MOV  r5, [r6 + 16]      ; r5: the word waiting for the next tile's
        MOV  r13, #20
.tile:  MOV  r6, [r2]+
        ADD  r6, r10
        MOV  r4, [r6]+
        OR   r5, r4
        MOV  [r3]+, r5
        MOV  r4, [r6]+
        MOV  [r3]+, r4
        MOV  r4, [r6]+
        MOV  [r3]+, r4
        MOV  r4, [r6]+
        MOV  [r3]+, r4
        MOV  r5, [r6]
        DBNZ r13, .tile
        MOV  r6, [r2]
        ADD  r6, r10
        MOV  r4, [r6]
        OR   r5, r4
        MOV  [r3], r5
        ADD  r8, r9
        ADD  r10, #20
        DEC  r12
        BNE  .line
        RESTORE r8-r14
        RET
