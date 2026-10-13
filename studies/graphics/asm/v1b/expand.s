; expand_rows(job): drawing a 1-bit source in colour, in draft 1b, for
; transparent drawing (glyphs, icons, the cursor); opaque goes to the C
; version (src/expand.c, which explains the job and the algorithm).
;
; ExpandJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24,
;            rmask 28, soff 32, slast 36, fg 40, bg 44, opaque 48,
;            depth 52, cfirst 56, clast 60, nch 64
;
; Per row the source is read in 32-bit chunks lined up with the
; destination words, (lo >> rs) | (hi << ls) as in blit.s, but with
; plain shifts, skipped for zero words: glyph rows are mostly zero words.
; A chunk covers 1, 2, 4 or 8 destination words, which are written until
; the chunk's bits run out, skipping the ones with nothing to draw. A word
; under mask m is (d & ~m) | (fg & m): MOV, BIC, AND, OR, ST.
;
; The fast path: a source that starts on a word and rows of one chunk,
; which is every glyph from a font strike or the glyph cache that fits
; in 32 bits from the start of its first destination word. A row is then
; one load, a shift left by the lead pixels and a mask, and the words. The
; general path loops over the chunks, with its counters in a frame, and
; calls an emit routine for the depth through a stack slot.

RS      = 0                     ; the frame (general path): the shifts,
LS      = 4                     ; LS = 0 if RS = 0
PRE     = 8                     ; the first source word is only lo
SRC     = 12                    ; source words left, minus 1
CHUNKS  = 16                    ; chunks left in the row
MASK    = 20                    ; for this chunk: cfirst, ~0 or clast
EMIT    = 24                    ; the emit routine
STEP    = 28                    ; bytes per chunk: 4 << depth
FRAME   = 32

        .global _expand_rows
        .section .text._expand_rows
_expand_rows:
        MOV  r2, [r1 + 48]
        BNE  _expand_rows_c     ; opaque
        SAVE r8-r14
        MOV  r8, [r1 + 40]      ; r8: fg
        MOV  r6, [r1 + 52]      ; the depth: its table
        LEA  r7, [pc + .tables]
        MOV  r7, [r7 + r6*4]    ; r7: the table
        MOV  r2, [r1]           ; r2/r3: the rows
        MOV  r3, [r1 + 4]
        MOV  r4, [r1 + 16]      ; r4: rows left
        BLE  .out
        MOV  r9, [r1 + 32]      ; soff
        BGT  .general
        MOV  r5, [r1 + 64]
        CMP  r5, #1
        BNE  .general
        NEG  r9                 ; r9: the lead
        MOV  r10, [r1 + 56]     ; r10: the mask
        LEA  r5, [pc + .fasts]
        JMP  [r5 + r6*4]

        .align 4
.fasts: .word .f0, .f1, .f2, .f3
.emits: .word .emit0, .emit1, .emit2, .emit3
.tables:
        .word 0, _gfx_x2, _gfx_x4, _gfx_x8

; ---- the fast path, a loop per depth ----

.f0:    MOV  r11, [r3]
        LSL  r11, r9
        AND  r11, r10
        BEQ  .f0n
        MOV  r6, [r2]
        BIC  r6, r11
        AND  r11, r8
        OR   r6, r11
        ST   r6, [r2]
.f0n:   ADD  r2, [r1 + 8]
        ADD  r3, [r1 + 12]
        DEC  r4
        BNE  .f0
.out:   RESTORE r8-r14
        RET

.f1:    MOV  r11, [r3]
        LSL  r11, r9
        AND  r11, r10
        BEQ  .f1n
        MOV  r14, r2
.f1l:   ZXB  r13, r11
        MOV  r5, [r7 + r13*4]
        LSR  r11, #8
        ZXB  r13, r11
        MOV  r13, [r7 + r13*4]
        SWAP r13
        OR   r5, r13
        BEQ  .f1z
        MOV  r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.f1z:   ADD  r14, #4
        LSR  r11, #8
        BNE  .f1l
.f1n:   ADD  r2, [r1 + 8]
        ADD  r3, [r1 + 12]
        DEC  r4
        BNE  .f1
        BRA  .out

.f2:    MOV  r11, [r3]
        LSL  r11, r9
        AND  r11, r10
        BEQ  .f2n
        MOV  r14, r2
.f2l:   ZXB  r13, r11
        MOV  r5, [r7 + r13*4]
        BEQ  .f2z
        MOV  r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.f2z:   ADD  r14, #4
        LSR  r11, #8
        BNE  .f2l
.f2n:   ADD  r2, [r1 + 8]
        ADD  r3, [r1 + 12]
        DEC  r4
        BNE  .f2
        BRA  .out

.f3:    MOV  r11, [r3]
        LSL  r11, r9
        AND  r11, r10
        BEQ  .f3n
        MOV  r14, r2
.f3l:   ZXB  r13, r11
        LEA  r13, [r7 + r13*8]
        MOV  r5, [r13]
        BEQ  .f3a
        MOV  r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.f3a:   MOV  r5, [r13 + 4]
        BEQ  .f3b
        MOV  r6, [r14 + 4]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14 + 4]
.f3b:   ADD  r14, #8
        LSR  r11, #8
        BNE  .f3l
.f3n:   ADD  r2, [r1 + 8]
        ADD  r3, [r1 + 12]
        DEC  r4
        BNE  .f3
        BRA  .out

; ---- the general path ----

.general:
        SUB  sp, #FRAME
        MOV  r5, #4
        LSL  r5, r6
        ST   r5, [sp + STEP]
        LEA  r5, [pc + .emits]
        MOV  r5, [r5 + r6*4]
        ST   r5, [sp + EMIT]
        MOV  r5, #0             ; soff: shift by rs = soff & 31; pre if soff >= 0
        CMP  r9, #0
        BLT  .neg
        MOV  r5, #1
.neg:   ST   r5, [sp + PRE]
        AND  r9, #31
        ST   r9, [sp + RS]
        BEQ  .ls
        NEG  r9
        ADD  r9, #32
.ls:    ST   r9, [sp + LS]

.row:   MOV  r9, r2
        MOV  r10, r3
        MOV  r5, [r1 + 36]      ; slast
        MOV  r12, #0
        MOV  r6, [sp + PRE]
        BEQ  .nopre
        MOV  r12, [r10]+
        DEC  r5
.nopre: ST   r5, [sp + SRC]
        MOV  r6, [r1 + 64]
        ST   r6, [sp + CHUNKS]
        MOV  r6, [r1 + 56]
        ST   r6, [sp + MASK]
.chunk: MOV  r13, #0            ; hi: the next source word, if any is left
        MOV  r5, [sp + SRC]
        BMI  .none
        MOV  r13, [r10]+
.none:  DEC  r5
        ST   r5, [sp + SRC]
        MOV  r11, r12           ; the chunk: (lo >> rs) | (hi << ls)
        BEQ  .lo0
        MOV  r6, [sp + RS]
        LSR  r11, r6
.lo0:   MOV  r12, r13           ; hi is the next lo
        BEQ  .hi0
        MOV  r6, [sp + LS]
        BEQ  .hi0
        LSL  r13, r6
        OR   r11, r13
.hi0:   AND  r11, [sp + MASK]
        BEQ  .empty
        MOV  r14, r9
        CALL [sp + EMIT]
.empty: ADD  r9, [sp + STEP]
        MOV  r5, [sp + CHUNKS]
        DEC  r5
        BEQ  .next
        ST   r5, [sp + CHUNKS]
        MOV  r6, #-1            ; a chunk in the middle
        CMP  r5, #1
        BNE  .mid
        MOV  r6, [r1 + 60]      ; the last
.mid:   ST   r6, [sp + MASK]
        BRA  .chunk
.next:  ADD  r2, [r1 + 8]
        ADD  r3, [r1 + 12]
        DEC  r4
        BNE  .row
        ADD  sp, #FRAME
        BRA  .out

; The emit routines: chunk r11 (not 0), destination r14.

.emit0: MOV  r6, [r14]
        BIC  r6, r11
        AND  r11, r8
        OR   r6, r11
        ST   r6, [r14]
        RET

.emit1: ZXB  r13, r11
        MOV  r5, [r7 + r13*4]
        LSR  r11, #8
        ZXB  r13, r11
        MOV  r13, [r7 + r13*4]
        SWAP r13
        OR   r5, r13
        BEQ  .e1z
        MOV  r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.e1z:   ADD  r14, #4
        LSR  r11, #8
        BNE  .emit1
        RET

.emit2: ZXB  r13, r11
        MOV  r5, [r7 + r13*4]
        BEQ  .e2z
        MOV  r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.e2z:   ADD  r14, #4
        LSR  r11, #8
        BNE  .emit2
        RET

.emit3: ZXB  r13, r11
        LEA  r13, [r7 + r13*8]
        MOV  r5, [r13]
        BEQ  .e3a
        MOV  r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.e3a:   MOV  r5, [r13 + 4]
        BEQ  .e3b
        MOV  r6, [r14 + 4]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14 + 4]
.e3b:   ADD  r14, #8
        LSR  r11, #8
        BNE  .emit3
        RET
