; gfx_desktop's text: bitmap fonts (studies/graphics/fonts.py's format)
; drawn on the 4-bit framebuffer, clipped to `clip`, the way Heron Mini's
; library expands them (studies/mini_gfx/gfx/asm/expand.s): a glyph's
; 1-bit row is shifted to the pixel it starts on, then each of its bytes
; makes a whole destination word through a table, so no 4-bit pixels are
; ever shifted.
;
; - draw_text: proportional text (sans12), transparent: a glyph's pixels
;   in the text colour, d ^= (d ^ fg) & expand[byte];
; - draw_cells: a terminal's row of opaque character cells (mono12, 7 x 15
;   each), every pixel of a cell its foreground or background colour, from
;   a table of the 256 words a byte of glyph makes in those two colours
;   (made once for each pair, and kept: set_colours).
;
; A font, as loaded: the first character, how many, the ascent, the
; strike's bytes a row, the glyph table and the strike. A glyph's entry
; (8 bytes): width, height, advance, x offset and y offset (signed), 0,
; and its column of the strike in words (a half).

PITCH = 320
F_FIRST = 0
F_COUNT = 4
F_ASC = 8
F_STRIDE = 12
F_TABLE = 16
F_STRIKE = 20
CELL_W = 7                      ; mono12's cell
CELL_H = 15

        .global text_init, set_colours, draw_text, draw_cells, text_fg
        .global font_mono_d, font_sans_d, solid
        .far fb, otabs, font_mono, font_sans

        .text

; text_init(): the expansion table and the two fonts' descriptions.
text_init:
        PUSH r7
        ; expand[b]: nibble i is 15 where bit i of b is set; from b >> 1's
        ; entry shifted a nibble, and b's bit 0
        MOV  r1, #expand
        CLR  [r1]
        MOV  r2, #1
.x:     MOV  r3, r2
        LSR  r3, #1
        MOV  r3, [r1 + r3*4]
        LSL  r3, #4
        TST  r2, #1
        BEQ  .x0
        OR   r3, #15
.x0:    MOV  [r1 + r2*4], r3
        INC  r2
        CMP  r2, #256
        BNE  .x
        MOV  r1, #font_mono_d
        MOV  r2, #font_mono
        BSR  font_load
        MOV  r1, #font_sans_d
        MOV  r2, #font_sans
        BSR  font_load
        JMP  [sp]+

; font_load(d, blob): the description at d of the font at blob
font_load:
        MOV  r3, byte [r2]
        MOV  [r1 + F_FIRST], r3
        MOV  r3, byte [r2 + 1]
        MOV  [r1 + F_COUNT], r3
        MOV  r4, byte [r2 + 2]
        MOV  [r1 + F_ASC], r4
        MOV  r4, half [r2 + 4]  ; the strike's words a row
        LSL  r4, #2
        MOV  [r1 + F_STRIDE], r4
        ADD  r2, #8
        MOV  [r1 + F_TABLE], r2
        LSL  r3, #3             ; 8 bytes a glyph
        ADD  r2, r3
        MOV  [r1 + F_STRIKE], r2
        RET

; set_colours(fg, bg): the opaque table for the pair, made if it isn't
; one of the four kept (then it replaces the one made longest ago).
; Sets otab.
set_colours:
        LSL  r1, #4
        OR   r1, r2             ; r1: the pair's key
        MOV  r3, #okeys
        CLR  r4
.find:  CMP  r1, [r3 + r4*4]
        BEQ  .have
        INC  r4
        CMP  r4, #4
        BNE  .find
        MOV  r4, [onext]        ; not kept: make it in the oldest
        MOV  [r3 + r4*4], r1
        MOV  r0, r4
        INC  r0
        AND  r0, #3
        MOV  [onext], r0
        MOV  r0, r4
        LSL  r0, #10            ; 1 KB a table
        ADD  r0, #otabs
        MOV  [otab], r0
        ; tab[b] = bg ^ (expand[b] & (fg ^ bg)), with fg and bg as words
        MOV  r3, r1
        AND  r3, #15
        MOV  r3, [solid + r3*4] ; r3: bg
        LSR  r1, #4
        MOV  r2, [solid + r1*4]
        XOR  r2, r3             ; r2: fg ^ bg
        MOV  r1, #expand
        MOV  r4, #256
.make:  MOV  r5, [r1]+
        AND  r5, r2
        XOR  r5, r3
        MOV  [r0]+, r5
        DBNZ r4, .make
        RET
.have:  LSL  r4, #10
        ADD  r4, #otabs
        MOV  [otab], r4
        RET

; draw_text(x, base, s, n): n characters from s in sans12, transparent, in
; text_fg, the pen from x on the baseline base; clipped. Once a glyph
; starts right of the clip, so do all the rest: the line stops there.
;
; A glyph: its box is gx = pen + x offset, gy = base + y offset, w x h;
; its rows inside the clip are rows r0 to r1 of it; it starts in word
; gx >> 3, at pixel p = gx mod 8, and covers at most three words (p + w
; <= 7 + 11). The frame: [sp] the pen, [sp + 4] base, [sp + 8] s, [sp +
; 12] characters left, [sp + 16] and [sp + 20] room for two registers.
draw_text:
        SAVE r7-r14
        SUB  sp, #24
        MOV  [sp], r1
        MOV  [sp + 4], r2
        MOV  [sp + 8], r3
        MOV  [sp + 12], r4
        MOV  r11, [text_fg]
        MOV  r11, [solid + r11*4]   ; r11: the colour, a word of it
        MOV  r12, #expand           ; r12: the expansion table
.char:  MOV  r0, [sp + 12]
        DEC  r0
        BMI  .done
        MOV  [sp + 12], r0
        MOV  r3, [sp + 8]
        MOV  r0, byte [r3]+
        MOV  [sp + 8], r3
        ; the glyph's entry: r3; skip it if the font hasn't one
        SUB  r0, [font_sans_d + F_FIRST]
        CMP  r0, [font_sans_d + F_COUNT]
        BHS  .char
        MOV  r3, [font_sans_d + F_TABLE]
        LEA  r3, [r3 + r0*8]
        MOV  r1, [sp]           ; r1: gx; the pen moves on
        MOV  r0, byte [r3 + 2]
        ADD  r0, r1
        MOV  [sp], r0
        MOV  r0, byte [r3 + 3]
        SXB  r0
        ADD  r1, r0
        CMP  r1, [clip_x1]
        BGE  .done              ; this and the rest are right of the clip
        MOVS r6, byte [r3]      ; r6: w
        BEQ  .char
        MOV  r0, r1
        ADD  r0, r6
        CMP  r0, [clip_x0]
        BLE  .char              ; left of the clip
        ; the rows inside the clip: r2 the first's y, r14 how many
        MOV  r2, byte [r3 + 4]
        SXB  r2
        ADD  r2, [sp + 4]       ; gy
        MOV  r14, byte [r3 + 1]
        ADD  r14, r2            ; gy + h
        CMP  r14, [clip_y1]
        BLE  .y1
        MOV  r14, [clip_y1]
.y1:    MOV  r13, r2            ; r13: gy
        CMP  r2, [clip_y0]
        BGE  .y0
        MOV  r2, [clip_y0]
.y0:    SUB  r14, r2
        BLE  .char              ; above or below the clip
        ; r3: the first row's bits in the strike, r4 the stride
        MOV  r4, [font_sans_d + F_STRIDE]
        MOV  r7, r2
        SUB  r7, r13            ; rows skipped at the top, usually none,
        BEQ  .top               ; times the stride
        MULU r0:r7, r4
.top:   MOV  r5, half [r3 + 6]
        LSL  r5, #2
        ADD  r7, r5
        MOV  r3, [font_sans_d + F_STRIKE]
        ADD  r3, r7
        ; the masks of the three words: all ones unless the glyph
        ; crosses the clip's sides
        MOV  r8, #-1
        MOV  r9, #-1
        MOV  r10, #-1
        MOV  r5, r1
        ASR  r5, #3             ; r5: the first word
        CMP  r1, [clip_x0]
        BLT  .masks
        MOV  r0, r1
        ADD  r0, r6
        CMP  r0, [clip_x1]
        BLE  .dst
.masks: MOV  [sp + 16], r1      ; clip_mask uses r0-r2
        MOV  [sp + 20], r2
        MOV  r1, r5
        BSR  clip_mask
        MOV  r8, r1
        MOV  r1, r5
        INC  r1
        BSR  clip_mask
        MOV  r9, r1
        MOV  r1, r5
        ADD  r1, #2
        BSR  clip_mask
        MOV  r10, r1
        MOV  r1, [sp + 16]
        MOV  r2, [sp + 20]
        ; r2: the first row's first word
.dst:   MOV  r0, r2
        LSL  r0, #8
        LSL  r2, #6
        ADD  r2, r0
        LSL  r5, #2
        ADD  r2, r5
        ADD  r2, #fb
        MOV  r5, r1
        AND  r5, #7             ; r5: p

; the rows: a row's bits shifted to p, then each byte that has any set
; through the table and into its word, d ^= (d ^ fg) & (expand & mask)
.row:   MOV  r0, [r3]
        ADD  r3, r4
        LSL  r0, r5
        BEQ  .next              ; an empty row
        ZXB  r1, r0
        BEQ  .w1
        MOV  r1, [r12 + r1*4]
        AND  r1, r8
        MOV  r6, [r2]
        MOV  r13, r6
        XOR  r13, r11
        AND  r13, r1
        XOR  r6, r13
        MOV  [r2], r6
.w1:    LSR  r0, #8
        ZXB  r1, r0
        BEQ  .w2
        MOV  r1, [r12 + r1*4]
        AND  r1, r9
        MOV  r6, [r2 + 4]
        MOV  r13, r6
        XOR  r13, r11
        AND  r13, r1
        XOR  r6, r13
        MOV  [r2 + 4], r6
.w2:    LSR  r0, #8             ; what's left is a byte at most
        BEQ  .next
        MOV  r1, [r12 + r0*4]
        AND  r1, r10
        MOV  r6, [r2 + 8]
        MOV  r13, r6
        XOR  r13, r11
        AND  r13, r1
        XOR  r6, r13
        MOV  [r2 + 8], r6
.next:  ADD  r2, #PITCH
        DEC  r14
        BNE  .row
        BRA  .char
.done:  ADD  sp, #24
        RESTORE r7-r14
        RET

; draw_cells(x, top, s, n, cols): a terminal's row of cols opaque cells
; of mono12 in the colours set_colours chose, from (x, top): n characters
; from s, then spaces; clipped.
;
; The rows inside the clip are the same for every cell: rows c0 to c1 of
; it. A cell's glyph covers rows t to t + h of it (t = the ascent + its y
; offset), so the rows go in three runs: background above the glyph, the
; glyph's, background below; any may be empty. A cell starts in word x >>
; 3 at pixel p = x mod 8 and covers two words, or one for p of 0 or 1;
; the glyph's rows are shifted by p + its x offset, and the words go under
; the cell's own mask (seven pixels from p) and the clip's.
;
; The frame: [sp] x, [sp + 4] s, [sp + 8] characters left, [sp + 12]
; cells left, [sp + 16] c0, [sp + 20] c1, [sp + 24] the address of the
; first clipped row's first word, [sp + 28] t, [sp + 32] t + h, [sp + 36]
; room for a register; cols is above the frame and the eight saved
; registers, at [sp + 72].
;
; Through the runs: r2 the row's first word, r3 the glyph's bits and r4
; its stride, r5 the shift, r6 1 for two words, r8 and r9 the words'
; masks, r11 the background (a word of it), r12 the opaque table, r13 the
; row of the cell we're at, r14 the rows of the run.
draw_cells:
        SAVE r7-r14
        SUB  sp, #40
        MOV  [sp], r1
        MOV  [sp + 4], r3
        MOV  [sp + 8], r4
        MOV  r0, [sp + 72]
        MOV  [sp + 12], r0
        MOV  r3, [clip_y0]      ; c0 and c1
        SUB  r3, r2
        BPL  .c0
        CLR  r3
.c0:    MOV  r4, [clip_y1]
        SUB  r4, r2
        CMP  r4, #CELL_H
        BLE  .c1
        MOV  r4, #CELL_H
.c1:    CMP  r3, r4
        BGE  .done              ; above or below the clip
        MOV  [sp + 16], r3
        MOV  [sp + 20], r4
        ADD  r2, r3             ; the first clipped row's address
        MOV  r0, r2
        LSL  r0, #8
        LSL  r2, #6
        ADD  r2, r0
        ADD  r2, #fb
        MOV  [sp + 24], r2
        MOV  r12, [otab]
        MOV  r11, [r12]         ; the table's entry for no pixels

.cell:  MOV  r0, [sp + 12]      ; cells left?
        DEC  r0
        BMI  .done
        MOV  [sp + 12], r0
        MOV  r1, [sp]           ; r1: x; r0: the next cell's
        MOV  r0, r1
        ADD  r0, #CELL_W
        MOV  [sp], r0
        CMP  r1, [clip_x1]
        BGE  .done              ; this cell and the rest are right of the clip
        MOV  r3, #' '           ; r3: the character, a space once s runs out
        MOV  r2, [sp + 8]
        DEC  r2
        BMI  .left
        MOV  [sp + 8], r2
        MOV  r2, [sp + 4]
        MOV  r3, byte [r2]+
        MOV  [sp + 4], r2
.left:  CMP  r0, [clip_x0]      ; left of the clip?
        BLE  .cell
        ; r8, r9: the words' masks, the cell's seven pixels from p
        MOV  r6, r1
        AND  r6, #7             ; r6: p
        MOV  r8, #0x7F
        LSL  r8, r6
        MOV  r9, r8
        LSR  r9, #8
        AND  r8, #255
        MOV  r8, [expand + r8*4]
        MOV  r9, [expand + r9*4]
        MOV  r5, r1
        ASR  r5, #3             ; r5: the first word
        CMP  r1, [clip_x0]      ; inside the clip's columns?
        BLT  .clipx
        CMP  r0, [clip_x1]
        BLE  .glyph
.clipx: MOV  [sp + 36], r3
        MOV  r1, r5
        BSR  clip_mask
        AND  r8, r1
        MOV  r1, r5
        INC  r1
        BSR  clip_mask
        AND  r9, r1
        MOV  r3, [sp + 36]
        ; the glyph's entry (a space for a character the font hasn't)
.glyph: MOV  r2, [sp + 24]
        LSL  r5, #2
        ADD  r2, r5
        SUB  r3, [font_mono_d + F_FIRST]
        CMP  r3, [font_mono_d + F_COUNT]
        BLO  .known
        MOV  r3, #' '
        SUB  r3, [font_mono_d + F_FIRST]
.known: MOV  r4, [font_mono_d + F_TABLE]
        LEA  r4, [r4 + r3*8]
        MOV  r13, byte [r4 + 4] ; t
        SXB  r13
        ADD  r13, [font_mono_d + F_ASC]
        MOV  [sp + 28], r13
        MOV  r0, byte [r4 + 1]  ; t + h
        ADD  r0, r13
        MOV  [sp + 32], r0
        MOV  r5, byte [r4 + 3]
        ADD  r5, r6             ; r5: p + the x offset
        MOV  r3, half [r4 + 6]
        LSL  r3, #2
        ADD  r3, [font_mono_d + F_STRIKE]
        MOV  r4, [font_mono_d + F_STRIDE]
        CMP  r6, #2
        SETHS r6                ; r6: two words?

        ; the runs: background from c0 to t, the glyph's rows to t + h,
        ; background to c1, each cut to c0...c1
        MOV  r13, [sp + 16]
        MOV  r14, [sp + 28]
        CMP  r14, [sp + 20]
        BLE  .r1
        MOV  r14, [sp + 20]
.r1:    SUB  r14, r13
        BLE  .glyphs
        ADD  r13, r14
        BSR  .bgrun
.glyphs:
        MOV  r14, [sp + 32]
        CMP  r14, [sp + 20]
        BLE  .r2
        MOV  r14, [sp + 20]
.r2:    SUB  r14, r13
        BLE  .below
        MOV  r1, r13            ; past the glyph's rows above c0
        SUB  r1, [sp + 28]
        BEQ  .top
        MULU r0:r1, r4
        ADD  r3, r1
.top:   ADD  r13, r14
        BSR  .fgrun
.below: MOV  r14, [sp + 20]
        SUB  r14, r13
        BLE  .cell
        BSR  .bgrun
        BRA  .cell
.done:  ADD  sp, #40
        RESTORE r7-r14
        RET

; .fgrun: r14 rows of the glyph: a row's bits shifted to the cell, a byte
; of them a word through the opaque table, d ^ ((d ^ v) & mask)
.fgrun: TST  r6, r6
        BEQ  .fg1
.fg2:   MOV  r0, [r3]
        ADD  r3, r4
        LSL  r0, r5
        ZXB  r1, r0
        MOV  r1, [r12 + r1*4]
        MOV  r10, [r2]
        XOR  r1, r10
        AND  r1, r8
        XOR  r10, r1
        MOV  [r2], r10
        LSR  r0, #8             ; the second byte, all that's left
        MOV  r1, [r12 + r0*4]
        MOV  r10, [r2 + 4]
        XOR  r1, r10
        AND  r1, r9
        XOR  r10, r1
        MOV  [r2 + 4], r10
        ADD  r2, #PITCH
        DEC  r14
        BNE  .fg2
        RET
.fg1:   MOV  r0, [r3]
        ADD  r3, r4
        LSL  r0, r5
        ZXB  r1, r0
        MOV  r1, [r12 + r1*4]
        MOV  r10, [r2]
        XOR  r1, r10
        AND  r1, r8
        XOR  r10, r1
        MOV  [r2], r10
        ADD  r2, #PITCH
        DEC  r14
        BNE  .fg1
        RET

; .bgrun: r14 rows of background
.bgrun: TST  r6, r6
        BEQ  .bg1
.bg2:   MOV  r0, [r2]
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
        BNE  .bg2
        RET
.bg1:   MOV  r0, [r2]
        MOV  r1, r0
        XOR  r1, r11
        AND  r1, r8
        XOR  r0, r1
        MOV  [r2], r0
        ADD  r2, #PITCH
        DEC  r14
        BNE  .bg1
        RET

        .data
        .align 4
; a colour as a word of it
solid:  .word 0x00000000, 0x11111111, 0x22222222, 0x33333333
        .word 0x44444444, 0x55555555, 0x66666666, 0x77777777
        .word 0x88888888, 0x99999999, 0xAAAAAAAA, 0xBBBBBBBB
        .word 0xCCCCCCCC, 0xDDDDDDDD, 0xEEEEEEEE, 0xFFFFFFFF
text_fg: .word 0                ; draw_text's colour
otab:   .word 0                 ; draw_cells' table
okeys:  .word -1, -1, -1, -1    ; the kept tables' colour pairs
onext:  .word 0                 ; the next to replace
font_mono_d: .space 24
font_sans_d: .space 24

        .bss
        .align 4
expand: .space 1024             ; a byte of glyph as a word of masks
        .section .farbss.otabs
        .align 4
otabs:  .space 4096             ; four opaque tables
