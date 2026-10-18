; The editors' text columns (text.c): one cell's (or one word's cells')
; 16 glyph rows written down the rows of a surface, for the asm and blk
; variants. The single cells are unrolled; the words of several cells
; loop with DBNZ.
;
;   void text_col1(unsigned *d, const unsigned char *g, const unsigned *t, int pitch)
;       a cell a word (4 bits a pixel): d = t[glyph row], 16 rows pitch bytes apart
;   void text_lin1(unsigned char *d, const unsigned char *g, unsigned inv, int pitch)
;       a cell a byte (1 bit, linear): d = glyph row ^ inv
;   void text_col2(unsigned *d, const ColJob *j), text_col4(...)
;       2 or 4 cells a word: d = OR of t_k[g_k row]
;
; ColJob: g[4] 0, t[4] 16, pitch 32

        .global _text_col1, _text_lin1, _text_col2, _text_col4

        .section .text._text_col1
_text_col1:
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        MOV  r0, [r3 + r0*4]
        MOV  [r1], r0
        RET

        .section .text._text_lin1
_text_lin1:
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        ADD  r1, r4
        MOV  r0, byte [r2]+
        XOR  r0, r3
        MOV  byte [r1], r0
        RET

        .section .text._text_col2
_text_col2:
        SAVE r7-r9
        MOV  r3, [r2]           ; the glyphs
        MOV  r4, [r2 + 4]
        MOV  r5, [r2 + 16]      ; the tables
        MOV  r6, [r2 + 20]
        MOV  r8, [r2 + 32]      ; the pitch
        MOV  r9, #16
.l:     MOV  r0, byte [r3]+
        MOV  r7, [r5 + r0*4]
        MOV  r0, byte [r4]+
        OR   r7, [r6 + r0*4]
        MOV  [r1], r7
        ADD  r1, r8
        DBNZ r9, .l
        RESTORE r7-r9
        RET

        .section .text._text_col4
_text_col4:
        SAVE r7-r13
        MOV  r3, [r2]           ; the glyphs
        MOV  r4, [r2 + 4]
        MOV  r5, [r2 + 8]
        MOV  r6, [r2 + 12]
        MOV  r7, [r2 + 16]      ; the tables
        MOV  r8, [r2 + 20]
        MOV  r9, [r2 + 24]
        MOV  r10, [r2 + 28]
        MOV  r11, [r2 + 32]     ; the pitch
        MOV  r13, #16
.l:     MOV  r0, byte [r3]+
        MOV  r12, [r7 + r0*4]
        MOV  r0, byte [r4]+
        OR   r12, [r8 + r0*4]
        MOV  r0, byte [r5]+
        OR   r12, [r9 + r0*4]
        MOV  r0, byte [r6]+
        OR   r12, [r10 + r0*4]
        MOV  [r1], r12
        ADD  r1, r11
        DBNZ r13, .l
        RESTORE r7-r13
        RET

; text_mask2(d, job), text_mask4(d, job): a word of 2 or 4 cells of one
; colour pair, bg ^ (fx & the OR of the cells' masks), 16 rows
; MaskJob: m[4] 0, fx 16, bg 20, pitch 24

        .global _text_mask2, _text_mask4

        .section .text._text_mask2
_text_mask2:
        SAVE r7-r9
        MOV  r3, [r2]           ; the masks
        MOV  r4, [r2 + 4]
        MOV  r5, [r2 + 16]      ; fx
        MOV  r6, [r2 + 20]      ; bg
        MOV  r8, [r2 + 24]      ; the pitch
        MOV  r9, #16
.l:     MOV  r0, [r3]+
        OR   r0, [r4]+
        AND  r0, r5
        XOR  r0, r6
        MOV  [r1], r0
        ADD  r1, r8
        DBNZ r9, .l
        RESTORE r7-r9
        RET

        .section .text._text_mask4
_text_mask4:
        SAVE r7-r10
        MOV  r3, [r2]           ; the masks
        MOV  r4, [r2 + 4]
        MOV  r5, [r2 + 8]
        MOV  r6, [r2 + 12]
        MOV  r7, [r2 + 16]      ; fx
        MOV  r8, [r2 + 20]      ; bg
        MOV  r9, [r2 + 24]      ; the pitch
        MOV  r10, #16
.l:     MOV  r0, [r3]+
        OR   r0, [r4]+
        OR   r0, [r5]+
        OR   r0, [r6]+
        AND  r0, r7
        XOR  r0, r8
        MOV  [r1], r0
        ADD  r1, r9
        DBNZ r10, .l
        RESTORE r7-r10
        RET

; text_run4(d, t, nwords, run), text_run2(...): words of 4 or 2 cells of one
; colour pair, each through text_mask4's loop: the cells' masks found from
; the characters at t (run->gofs: a glyph's offset in a place's masks;
; place j's masks at run->mf + 6144 * j)
; MaskRun: mf 0, gofs 4, fx 8, bg 12, pitch 16

        .global _text_run4, _text_run2

        .section .text._text_run4
_text_run4:
        SAVE r7-r14
        MOV  r13, [r4]          ; the mask font
        MOV  r12, [r4 + 4]      ; the glyphs' offsets
        MOV  r8, [r4 + 8]       ; fx
        MOV  r9, [r4 + 12]      ; bg
        MOV  r10, [r4 + 16]     ; the pitch
.word:  MOV  r14, r1            ; the word's top
        MOVS r0, byte [r2]+     ; its four cells' masks
        MOV  r4, [r12 + r0*4]
        ADD  r4, r13
        MOVS r0, byte [r2]+
        MOV  r5, [r12 + r0*4]
        ADD  r5, r13
        ADD  r5, #6144
        MOVS r0, byte [r2]+
        MOV  r6, [r12 + r0*4]
        ADD  r6, r13
        ADD  r6, #12288
        MOVS r0, byte [r2]+
        MOV  r7, [r12 + r0*4]
        ADD  r7, r13
        ADD  r7, #18432
        MOV  r11, #16
.l:     MOV  r0, [r4]+
        OR   r0, [r5]+
        OR   r0, [r6]+
        OR   r0, [r7]+
        AND  r0, r8
        XOR  r0, r9
        MOV  [r1], r0
        ADD  r1, r10
        DBNZ r11, .l
        LEA  r1, [r14 + 4]      ; the next word
        DEC  r3
        BNE  .word
        RESTORE r7-r14
        RET

        .section .text._text_run2
_text_run2:
        SAVE r7-r14
        MOV  r13, [r4]
        MOV  r12, [r4 + 4]
        MOV  r8, [r4 + 8]
        MOV  r9, [r4 + 12]
        MOV  r10, [r4 + 16]
.word:  MOV  r14, r1
        MOVS r0, byte [r2]+
        MOV  r4, [r12 + r0*4]
        ADD  r4, r13
        MOVS r0, byte [r2]+
        MOV  r5, [r12 + r0*4]
        ADD  r5, r13
        ADD  r5, #6144
        MOV  r11, #16
.l:     MOV  r0, [r4]+
        OR   r0, [r5]+
        AND  r0, r8
        XOR  r0, r9
        MOV  [r1], r0
        ADD  r1, r10
        DBNZ r11, .l
        LEA  r1, [r14 + 4]
        DEC  r3
        BNE  .word
        RESTORE r7-r14
        RET
