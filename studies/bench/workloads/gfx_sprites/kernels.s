; gfx_sprites' kernels: tiles, copies, saving and restoring under
; sprites, masked sprites, shifting the sprites' art, the status line's
; text, and the screen's checksum. They work on whole words, as the RTS's
; and the platformer's kernels do (studies/mini_gfx/games/rts/kern.s,
; games/platformer/kernels.s): the sprites are shifted to their pixel
; once, at start-up, so drawing one is (d & keep) | image a word at a time.
;
; The framebuffer is 640 x 480, 320 bytes a row, Heron Mini's M0 layout:
; pixel p of a word is bits 4p to 4p + 3, so a row's pixels run from a
; word's low nibble to its high one. The C calling convention throughout:
; arguments in r1-r4 then on the stack, r0-r7 the caller's to save,
; r8-r14 the callee's.

PITCH = 320
CELL_W = 7                      ; mono12's cell
CELL_H = 15
F_FIRST = 0                     ; a font, as loaded (text_init)
F_COUNT = 4
F_ASC = 8
F_STRIDE = 12
F_TABLE = 16
F_STRIKE = 20

        .global fb, row_addr, tile_draw, tile_column, copy_words, fill_words
        .global save_rect, restore_rect, sprite_draw, preshift, shifted
        .global text_init, draw_cells, checksum
        .far fb, shifted, sprite_art, font_mono

        .text

; row_addr(y): r1 = the address of row y's first word. y * 320 as
; y * 256 + y * 64. Uses r0.
row_addr:
        MOV  r0, r1
        LSL  r1, #8
        LSL  r0, #6
        ADD  r1, r0
        ADD  r1, #fb
        RET

; tile_draw(at, tile): a 16 x 16 tile, its rows two words each, one
; after the other
tile_draw:
        MOV  r3, #16
.row:   MOV  r0, [r2]+
        MOV  [r1], r0
        MOV  r0, [r2]+
        MOV  [r1 + 4], r0
        ADD  r1, #PITCH
        DBNZ r3, .row
        RET

; tile_column(at, src): one word (8 pixels) of each of a tile's 16 rows,
; from src, the tile's left or right half (its rows are 8 bytes apart)
tile_column:
        MOV  r3, #16
.row:   MOV  r0, [r2]
        MOV  [r1], r0
        ADD  r2, #8
        ADD  r1, #PITCH
        DBNZ r3, .row
        RET

; copy_words(d, s, n, rows): rows of n words from s to d, both a screen's
; row apart, left to right (so d may be just left of s): four loads and
; stores a loop, then the rest (LDM and STM are slower, report 0043).
copy_words:
        SAVE r8-r11
        MOV  r8, r3
        LSR  r8, #2             ; r8: fours a row
        AND  r3, #3             ; r3: then single words
.row:   MOV  r9, r1
        MOV  r10, r2
        MOVS r11, r8
        BEQ  .rest
.w4:    MOV  r0, [r10]+
        MOV  [r9]+, r0
        MOV  r0, [r10]+
        MOV  [r9]+, r0
        MOV  r0, [r10]+
        MOV  [r9]+, r0
        MOV  r0, [r10]+
        MOV  [r9]+, r0
        DBNZ r11, .w4
.rest:  MOVS r11, r3
        BEQ  .next
.w1:    MOV  r0, [r10]+
        MOV  [r9]+, r0
        DBNZ r11, .w1
.next:  ADD  r1, #PITCH
        ADD  r2, #PITCH
        DEC  r4
        BNE  .row
        RESTORE r8-r11
        RET

; fill_words(at, v, n, rows): rows of n words set to v
fill_words:
.row:   MOV  r5, r1
        MOV  r6, r3
.w:     MOV  [r5]+, r2
        DBNZ r6, .w
        ADD  r1, #PITCH
        DBNZ r4, .row
        RET

; save_rect(buf, at, n, rows): rows of n (1-3) words of the screen from
; at, packed into buf: what's under a sprite
save_rect:
        CMP  r3, #2
        BEQ  .n2
        BHI  .n3
.n1:    MOV  r0, [r2]
        MOV  [r1]+, r0
        ADD  r2, #PITCH
        DBNZ r4, .n1
        RET
.n2:    MOV  r0, [r2]
        MOV  [r1]+, r0
        MOV  r0, [r2 + 4]
        MOV  [r1]+, r0
        ADD  r2, #PITCH
        DBNZ r4, .n2
        RET
.n3:    MOV  r0, [r2]
        MOV  [r1]+, r0
        MOV  r0, [r2 + 4]
        MOV  [r1]+, r0
        MOV  r0, [r2 + 8]
        MOV  [r1]+, r0
        ADD  r2, #PITCH
        DBNZ r4, .n3
        RET

; restore_rect(at, buf, n, rows): save_rect's words put back
restore_rect:
        CMP  r3, #2
        BEQ  .n2
        BHI  .n3
.n1:    MOV  r0, [r2]+
        MOV  [r1], r0
        ADD  r1, #PITCH
        DBNZ r4, .n1
        RET
.n2:    MOV  r0, [r2]+
        MOV  [r1], r0
        MOV  r0, [r2]+
        MOV  [r1 + 4], r0
        ADD  r1, #PITCH
        DBNZ r4, .n2
        RET
.n3:    MOV  r0, [r2]+
        MOV  [r1], r0
        MOV  r0, [r2]+
        MOV  [r1 + 4], r0
        MOV  r0, [r2]+
        MOV  [r1 + 8], r0
        ADD  r1, #PITCH
        DBNZ r4, .n3
        RET

; sprite_draw(at, src, n, rows): a shifted sprite's rows into the screen:
; n (1-3) words a row from src, whose rows are three (keep, image) pairs
; (24 bytes; a sprite clipped at a side uses some of them), and each word
; d = (d & keep) | image
sprite_draw:
        CMP  r3, #2
        BEQ  .n2
        BHI  .n3
.n1:    MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1], r0
        ADD  r2, #16
        ADD  r1, #PITCH
        DBNZ r4, .n1
        RET
.n2:    MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1], r0
        MOV  r0, [r1 + 4]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1 + 4], r0
        ADD  r2, #8
        ADD  r1, #PITCH
        DBNZ r4, .n2
        RET
.n3:    MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1], r0
        MOV  r0, [r1 + 4]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1 + 4], r0
        MOV  r0, [r1 + 8]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1 + 8], r0
        ADD  r1, #PITCH
        DEC  r4
        BNE  .n3
        RET

; preshift(): every kind of sprite_art (16 rows of image and mask, two
; words each) shifted to each pixel p of a word, into `shifted`: kind k
; at p is 384 bytes at (8k + p) x 384, 16 rows of three (keep, image)
; pairs. With s = 4p the 64 bits of a row become three words, lo << s,
; lo >> 32 - s | hi << s and hi >> 32 - s; keep is the mask's complement.
; The shifts are by a register: done once, they needn't be fast.
preshift:
        SAVE r7-r13
        MOV  r1, #sprite_art    ; r1: the art's row
        MOV  r2, #shifted       ; r2: the next pair
        MOV  r3, #NKIND         ; r3: kinds left
.kind:  CLR  r4                 ; r4: s
.shift: MOV  r5, r1             ; r5: this kind's rows
        MOV  r6, #16
        MOV  r7, #32
        SUB  r7, r4             ; r7: 32 - s
.row:   MOV  r8, [r5]           ; r8, r9: the image; r10, r11: the mask
        MOV  r9, [r5 + 4]
        MOV  r10, [r5 + 8]
        MOV  r11, [r5 + 12]
        ADD  r5, #16
        TST  r4, r4
        BNE  .sh
        NOT  r10                ; on a word: the two words, and a third
        MOV  [r2]+, r10         ; that keeps everything
        MOV  [r2]+, r8
        NOT  r11
        MOV  [r2]+, r11
        MOV  [r2]+, r9
        MOV  r0, #-1
        MOV  [r2]+, r0
        CLR  [r2]+
        BRA  .next
.sh:    MOV  r0, r10            ; word 0
        LSL  r0, r4
        NOT  r0
        MOV  [r2]+, r0
        MOV  r0, r8
        LSL  r0, r4
        MOV  [r2]+, r0
        MOV  r0, r10            ; word 1
        LSR  r0, r7
        MOV  r12, r11
        LSL  r12, r4
        OR   r0, r12
        NOT  r0
        MOV  [r2]+, r0
        MOV  r0, r8
        LSR  r0, r7
        MOV  r12, r9
        LSL  r12, r4
        OR   r0, r12
        MOV  [r2]+, r0
        LSR  r11, r7            ; word 2
        NOT  r11
        MOV  [r2]+, r11
        LSR  r9, r7
        MOV  [r2]+, r9
.next:  DEC  r6
        BNE  .row
        ADD  r4, #4
        CMP  r4, #32
        BNE  .shift
        ADD  r1, #256           ; the next kind's art
        DEC  r3
        BNE  .kind
        RESTORE r7-r13
        RET

; ---- text ----------------------------------------------------------------------------
;
; The status line's text: mono12 (studies/graphics/fonts.py's format) in
; opaque character cells of 7 x 15, as gfx_desktop's terminals draw them
; but never clipped. A glyph's 1-bit row is shifted to its pixel in the
; cell's first word, and each byte of it makes a whole word through a
; table of the 256 words a byte makes in the two colours, so no 4-bit
; pixel is ever shifted.

; text_init(fg, bg): the font's description, and the table for the
; colours: tab[b] = bg ^ (expand[b] & (fg ^ bg)), where expand[b] has
; nibble i 15 if bit i of b is set
text_init:
        MOV  r3, #font_d
        MOV  r4, #font_mono
        MOV  r0, byte [r4]
        MOV  [r3 + F_FIRST], r0
        MOV  r0, byte [r4 + 1]
        MOV  [r3 + F_COUNT], r0
        MOV  r5, r0
        MOV  r0, byte [r4 + 2]
        MOV  [r3 + F_ASC], r0
        MOV  r0, half [r4 + 4]
        LSL  r0, #2
        MOV  [r3 + F_STRIDE], r0
        ADD  r4, #8
        MOV  [r3 + F_TABLE], r4
        LSL  r5, #3
        ADD  r4, r5
        MOV  [r3 + F_STRIKE], r4
        ; the colours as words: c x 0x11111111
        MOV  r0, #0x11111111
        MULU r0:r1, r0          ; r1: fg (r0: the product's high half, 0)
        MOV  r0, #0x11111111
        MULU r0:r2, r0          ; r2: bg
        XOR  r1, r2             ; r1: fg ^ bg
        ; expand[b], from b >> 1's shifted a nibble and b's bit 0, made
        ; and used in the same pass
        MOV  r3, #expand
        MOV  r4, #otab
        CLR  [r3]
        MOV  [r4], r2
        MOV  r5, #1
.x:     MOV  r6, r5
        LSR  r6, #1
        MOV  r6, [r3 + r6*4]
        LSL  r6, #4
        TST  r5, #1
        BEQ  .x0
        OR   r6, #15
.x0:    MOV  [r3 + r5*4], r6
        AND  r6, r1
        XOR  r6, r2
        MOV  [r4 + r5*4], r6
        INC  r5
        CMP  r5, #256
        BNE  .x
        RET

; draw_cells(x, top, s, n): n characters from s in opaque cells from
; (x, top). A cell's glyph covers rows t to t + h of it (t = the ascent +
; its y offset): background rows above, the glyph's, background below. A
; cell starts in word x >> 3 at pixel p = x mod 8 and covers two words
; (one for p of 0 or 1: then the second's mask is 0 and it's done
; anyway); the words go under the cell's own mask, seven pixels from p.
;
; Through a cell: r2 its row's first word, r3 the glyph's bits and r4 the
; strike's stride, r5 the shift, r8 and r9 the words' masks, r11 the
; background word, r12 the table, r13 the glyph's rows, r14 rows of a run.
; The frame: [sp] x, [sp + 4] s, [sp + 8] characters left, [sp + 12] the
; background rows below the glyph.
draw_cells:
        SAVE r7-r14
        SUB  sp, #16
        MOV  [sp], r1
        MOV  [sp + 4], r3
        MOV  [sp + 8], r4
        MOV  r1, r2
        BSR  row_addr
        MOV  r10, r1            ; r10: the top row's first word
        MOV  r12, #otab
        MOV  r11, [r12]
.cell:  MOV  r0, [sp + 8]
        DEC  r0
        BMI  .done
        MOV  [sp + 8], r0
        MOV  r1, [sp]           ; r1: x
        MOV  r0, r1
        ADD  r0, #CELL_W
        MOV  [sp], r0
        MOV  r3, [sp + 4]
        MOV  r0, byte [r3]+     ; r0: the character
        MOV  [sp + 4], r3
        MOV  r6, r1
        AND  r6, #7             ; r6: p
        MOV  r8, #0x7F          ; the masks
        LSL  r8, r6
        MOV  r9, r8
        LSR  r9, #8
        AND  r8, #255
        MOV  r8, [expand + r8*4]
        MOV  r9, [expand + r9*4]
        ASR  r1, #3
        LSL  r1, #2
        MOV  r2, r10
        ADD  r2, r1             ; r2: the cell's first word
        SUB  r0, [font_d + F_FIRST]
        MOV  r4, [font_d + F_TABLE]
        LEA  r4, [r4 + r0*8]    ; r4: the glyph's entry
        MOV  r14, byte [r4 + 4]
        SXB  r14
        ADD  r14, [font_d + F_ASC]  ; r14: t, the rows above
        MOV  r13, byte [r4 + 1]     ; r13: h
        MOV  r0, #CELL_H
        SUB  r0, r14
        SUB  r0, r13
        MOV  [sp + 12], r0          ; and the rows below
        MOV  r5, byte [r4 + 3]
        ADD  r5, r6             ; r5: p + the x offset
        MOV  r3, half [r4 + 6]
        LSL  r3, #2
        ADD  r3, [font_d + F_STRIKE]
        MOV  r4, [font_d + F_STRIDE]
        TST  r14, r14           ; background above
        BEQ  .glyph
        BSR  .bgrun
.glyph: MOVS r14, r13           ; the glyph's rows
        BEQ  .below
.fg:    MOV  r0, [r3]
        ADD  r3, r4
        LSL  r0, r5
        ZXB  r1, r0
        MOV  r1, [r12 + r1*4]
        MOV  r6, [r2]
        XOR  r1, r6
        AND  r1, r8
        XOR  r6, r1
        MOV  [r2], r6
        LSR  r0, #8
        MOV  r1, [r12 + r0*4]
        MOV  r6, [r2 + 4]
        XOR  r1, r6
        AND  r1, r9
        XOR  r6, r1
        MOV  [r2 + 4], r6
        ADD  r2, #PITCH
        DEC  r14
        BNE  .fg
.below: MOVS r14, [sp + 12]     ; background below
        BEQ  .cell
        BSR  .bgrun
        BRA  .cell
.done:  ADD  sp, #16
        RESTORE r7-r14
        RET

; .bgrun: r14 rows of background in the cell's two words
.bgrun: MOV  r0, [r2]
        MOV  r1, r0
        XOR  r1, r11
        AND  r1, r8
        XOR  r0, r1
        MOV  [r2], r0
        MOV  r0, [r2 + 4]
        MOV  r1, r0
        XOR  r1, r11
        AND  r1, r9
        XOR  r0, r1
        MOV  [r2 + 4], r0
        ADD  r2, #PITCH
        DEC  r14
        BNE  .bgrun
        RET

; checksum(): r1 = the sum of the screen's words, r2 = the sum of those
; sums, a word after another (Fletcher's second sum), four words a loop
checksum:
        MOV  r3, #fb
        MOV  r4, #SH
        CLR  r1
        CLR  r2
.row:   MOV  r5, #SW / 32
        MOV  r6, r3
.w4:    ADD  r1, [r6]+
        ADD  r2, r1
        ADD  r1, [r6]+
        ADD  r2, r1
        ADD  r1, [r6]+
        ADD  r2, r1
        ADD  r1, [r6]+
        ADD  r2, r1
        DBNZ r5, .w4
        ADD  r3, #PITCH
        DEC  r4
        BNE  .row
        RET

        .data
        .align 4
font_d: .space 24               ; mono12, as text_init loads it

        .bss
        .align 4
expand: .space 1024             ; a byte of glyph as a word of masks
otab:   .space 1024             ; ... and as a word of the two colours

        .section .farbss.shifted
        .align 4
shifted: .space NKIND * 8 * 384 ; the sprites shifted to each pixel

        .section .farbss.fb
        .align 4
fb:     .space PITCH * 480
