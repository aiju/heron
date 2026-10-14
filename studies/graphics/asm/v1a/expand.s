; expand_rows(job): drawing a 1-bit source in colour, in draft 1a, for
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
; under mask m is (d & ~m) | (fg & m): LD, BIC, AND, OR, ST.
;
; The fast path: a source that starts on a word and rows of one chunk,
; which is every glyph from a font strike or the glyph cache that fits
; in 32 bits from the start of its first destination word. A row is then
; one load, a shift left by the lead pixels and a mask, and the words. The
; general path loops over the chunks, with its counters in a frame, and
; calls an emit routine for the depth.

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
        LD   r2, [r1 + 48]
        BNE  _expand_rows_c     ; opaque
        SAVE r8-r14
        LD   r8, [r1 + 40]      ; r8: fg
        LD   r6, [r1 + 52]      ; the depth: its table
        MOV  r5, r6
        LSL  r5, #2
        LEA  r7, .tables
        ADD  r7, r5
        LD   r7, [r7]           ; r7: the table
        LD   r2, [r1]           ; r2/r3: the rows
        LD   r3, [r1 + 4]
        LD   r4, [r1 + 16]      ; r4: rows left
        BLE  .out
        LD   r9, [r1 + 32]      ; soff
        BGT  .general
        LD   r12, [r1 + 64]
        CMPI r12, 1
        BNE  .general
        NEG  r9                 ; r9: the lead
        LD   r10, [r1 + 56]     ; r10: the mask
        LD   r11, [r1 + 8]      ; r11/r12: the pitches
        LD   r12, [r1 + 12]
        LEA  r1, .fasts
        ADD  r1, r5
        LD   r1, [r1]
        JMP  r1

        .align 4
.fasts: .word .f0, .f1, .f2, .f3
.emits: .word .emit0, .emit1, .emit2, .emit3
.tables:
        .word 0, _gfx_x2, _gfx_x4, _gfx_x8

; ---- the fast path, a loop per depth; r11/r12 the pitches, r1 the chunk ----

.f0:    LD   r1, [r3]
        LSL  r1, r9
        AND  r1, r10
        BEQ  .f0n
        LD   r6, [r2]
        BIC  r6, r1
        AND  r1, r8
        OR   r6, r1
        ST   r6, [r2]
.f0n:   ADD  r2, r11
        ADD  r3, r12
        DEC  r4
        BNE  .f0
.out:   RESTORE r8-r14
        RET

.f1:    LD   r1, [r3]
        LSL  r1, r9
        AND  r1, r10
        BEQ  .f1n
        MOV  r14, r2
.f1l:   ZXB  r13, r1
        LSL  r13, #2
        ADD  r13, r7
        LD   r5, [r13]
        LSR  r1, #8
        ZXB  r13, r1
        LSL  r13, #2
        ADD  r13, r7
        LD   r13, [r13]
        SWAP r13
        OR   r5, r13
        BEQ  .f1z
        LD   r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.f1z:   ADDI r14, 4
        LSR  r1, #8
        BNE  .f1l
.f1n:   ADD  r2, r11
        ADD  r3, r12
        DEC  r4
        BNE  .f1
        BRA  .out

.f2:    LD   r1, [r3]
        LSL  r1, r9
        AND  r1, r10
        BEQ  .f2n
        MOV  r14, r2
.f2l:   ZXB  r13, r1
        LSL  r13, #2
        ADD  r13, r7
        LD   r5, [r13]
        BEQ  .f2z
        LD   r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.f2z:   ADDI r14, 4
        LSR  r1, #8
        BNE  .f2l
.f2n:   ADD  r2, r11
        ADD  r3, r12
        DEC  r4
        BNE  .f2
        BRA  .out

.f3:    LD   r1, [r3]
        LSL  r1, r9
        AND  r1, r10
        BEQ  .f3n
        MOV  r14, r2
.f3l:   ZXB  r13, r1
        LSL  r13, #3
        ADD  r13, r7
        LD   r5, [r13]
        BEQ  .f3a
        LD   r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.f3a:   LD   r5, [r13 + 4]
        BEQ  .f3b
        LD   r6, [r14 + 4]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14 + 4]
.f3b:   ADDI r14, 8
        LSR  r1, #8
        BNE  .f3l
.f3n:   ADD  r2, r11
        ADD  r3, r12
        DEC  r4
        BNE  .f3
        BRA  .out

; ---- the general path ----

.general:
        ADDI sp, -FRAME
        MVI  r6, 4
        LD   r12, [r1 + 52]
        LSL  r6, r12
        ST   r6, [sp + STEP]
        LEA  r6, .emits
        ADD  r6, r5
        LD   r6, [r6]
        ST   r6, [sp + EMIT]
        MVI  r5, 0              ; soff: shift by rs = soff & 31; pre if soff >= 0
        CMPI r9, 0
        BLT  .neg
        MVI  r5, 1
.neg:   ST   r5, [sp + PRE]
        AND  r9, #31
        ST   r9, [sp + RS]
        BEQ  .ls
        NEG  r9
        ADDI r9, 32
.ls:    ST   r9, [sp + LS]

.row:   MOV  r9, r2
        MOV  r10, r3
        LD   r5, [r1 + 36]      ; slast
        MVI  r12, 0
        LD   r6, [sp + PRE]
        BEQ  .nopre
        LD   r12, [r10]
        ADDI r10, 4
        DEC  r5
.nopre: ST   r5, [sp + SRC]
        LD   r6, [r1 + 64]
        ST   r6, [sp + CHUNKS]
        LD   r6, [r1 + 56]
        ST   r6, [sp + MASK]
.chunk: MVI  r13, 0             ; hi: the next source word, if any is left
        LD   r5, [sp + SRC]
        BMI  .none
        LD   r13, [r10]
        ADDI r10, 4
.none:  DEC  r5
        ST   r5, [sp + SRC]
        MOV  r11, r12           ; the chunk: (lo >> rs) | (hi << ls)
        BEQ  .lo0
        LD   r6, [sp + RS]
        LSR  r11, r6
.lo0:   MOV  r12, r13           ; hi is the next lo
        BEQ  .hi0
        LD   r6, [sp + LS]
        BEQ  .hi0
        LSL  r13, r6
        OR   r11, r13
.hi0:   LD   r6, [sp + MASK]
        AND  r11, r6
        BEQ  .empty
        MOV  r14, r9
        LD   r6, [sp + EMIT]
        CALL r6
.empty: LD   r6, [sp + STEP]
        ADD  r9, r6
        LD   r5, [sp + CHUNKS]
        DEC  r5
        BEQ  .next
        ST   r5, [sp + CHUNKS]
        MVI  r6, -1             ; a chunk in the middle
        CMPI r5, 1
        BNE  .mid
        LD   r6, [r1 + 60]      ; the last
.mid:   ST   r6, [sp + MASK]
        BRA  .chunk
.next:  LD   r6, [r1 + 8]
        ADD  r2, r6
        LD   r6, [r1 + 12]
        ADD  r3, r6
        DEC  r4
        BNE  .row
        ADDI sp, FRAME
        BRA  .out

; The emit routines: chunk r11 (not 0), destination r14.

.emit0: LD   r6, [r14]
        BIC  r6, r11
        AND  r11, r8
        OR   r6, r11
        ST   r6, [r14]
        RET

.emit1: ZXB  r13, r11
        LSL  r13, #2
        ADD  r13, r7
        LD   r5, [r13]
        LSR  r11, #8
        ZXB  r13, r11
        LSL  r13, #2
        ADD  r13, r7
        LD   r13, [r13]
        SWAP r13
        OR   r5, r13
        BEQ  .e1z
        LD   r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.e1z:   ADDI r14, 4
        LSR  r11, #8
        BNE  .emit1
        RET

.emit2: ZXB  r13, r11
        LSL  r13, #2
        ADD  r13, r7
        LD   r5, [r13]
        BEQ  .e2z
        LD   r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.e2z:   ADDI r14, 4
        LSR  r11, #8
        BNE  .emit2
        RET

.emit3: ZXB  r13, r11
        LSL  r13, #3
        ADD  r13, r7
        LD   r5, [r13]
        BEQ  .e3a
        LD   r6, [r14]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14]
.e3a:   LD   r5, [r13 + 4]
        BEQ  .e3b
        LD   r6, [r14 + 4]
        BIC  r6, r5
        AND  r5, r8
        OR   r6, r5
        ST   r6, [r14 + 4]
.e3b:   ADDI r14, 8
        LSR  r11, #8
        BNE  .emit3
        RET
