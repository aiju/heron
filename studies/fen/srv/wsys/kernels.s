; The graphics library's kernels (studies/graphics/src/gfx.h) in draft 2,
; for the window system, which compiles the library with GFX_ASM. Only
; what the window system spends its time on is here: fills and blits that
; copy. Everything else, and every other kernel, goes to the C version.
;
; FillJob: p 0, pitch 4, h 8, lmask 12, n 16, rmask 20, pat 24, rop 28
; BlitJob: d 0, s 4, dpitch 8, spitch 12, h 16, n 20, lmask 24, rmask 28,
;          rs 32, ls 36, pre 40, last 44, back 48, rop 52

        .far _fill_rows_c, _blit_rows_c, _line_run_c, _expand_rows_c, _ramp_rows_c, _gfx_span_c
        .global _fill_rows, _blit_rows, _line_run, _expand_rows, _ramp_rows, _gfx_span

        .text

_line_run:
        JMP  _line_run_c
_expand_rows:
        JMP  _expand_rows_c
_ramp_rows:
        JMP  _ramp_rows_c
_gfx_span:
        JMP  _gfx_span_c

; fill_rows(job): a COPY stores the pattern, four words at a time with
; STM; the edges are (v & ~m) | (pat & m)
_fill_rows:
        MOVS r0, [r1 + 28]
        BEQ  .fcopy
        JMP  _fill_rows_c
.fcopy: MOV  r0, [r1 + 8]
        CMP  r0, #0
        BLE  .fret
        SAVE r8-r14
        MOV  r2, [r1]           ; r2: the row
        MOV  r3, [r1 + 4]       ; r3: the pitch
        MOV  r4, r0             ; r4: rows left
        MOV  r5, [r1 + 12]      ; r5: lmask
        MOV  r6, [r1 + 16]      ; r6: whole words
        MOV  r8, [r1 + 24]      ; r8-r11: the pattern
        MOV  r9, r8
        MOV  r10, r8
        MOV  r11, r8
        MOV  r12, [r1 + 20]     ; r12: rmask
        MOV  r13, r8
        AND  r13, r5            ; r13: pat & lmask
        MOV  r14, r8
        AND  r14, r12           ; r14: pat & rmask
.frow:  MOV  r1, r2
        MOV  r0, [r1]
        BIC  r0, r5
        OR   r0, r13
        MOV  [r1]+, r0
        MOV  r0, r6
        LSR  r0, #2
        BEQ  .frem
.f4:    STM  r1, r8-r11
        ADD  r1, #16
        DBNZ r0, .f4
.frem:  MOV  r0, r6
        AND  r0, #3
        BEQ  .flast
.f1:    MOV  [r1]+, r8
        DBNZ r0, .f1
.flast: TST  r12, r12
        BEQ  .fnext
        MOV  r0, [r1]
        BIC  r0, r12
        OR   r0, r14
        MOV  [r1], r0
.fnext: ADD  r2, r3
        DEC  r4
        BNE  .frow
        RESTORE r8-r14
.fret:  RET

; blit_rows(job): a COPY from left to right. Without a shift (ls = 0, and
; then pre = 0 and last = 1) the whole words go four at a time with LDM
; and STM; with one, a word at a time as (lo >> rs) | (hi << ls). The
; edges are merged as d ^ ((d ^ v) & m).
_blit_rows:
        MOV  r0, [r1 + 52]
        OR   r0, [r1 + 48]
        BEQ  .bfwd
        JMP  _blit_rows_c
.bfwd:  MOV  r0, [r1 + 16]
        CMP  r0, #0
        BLE  .bret
        SAVE r8-r14
        MOVS r0, [r1 + 36]
        BNE  .shift
; no shift: r4 the row, r5 its source, r6 rows left, r12 n, r8-r11 a block
        MOV  r4, [r1]
        MOV  r5, [r1 + 4]
        MOV  r6, [r1 + 16]
        MOV  r12, [r1 + 20]
.urow:  MOV  r2, r4
        MOV  r3, r5
        MOV  r13, [r3]+         ; k = 0
        MOV  r14, [r2]
        XOR  r13, r14
        AND  r13, [r1 + 24]
        XOR  r14, r13
        MOV  [r2]+, r14
        MOVS r0, r12
        BEQ  .unext
        SUB  r0, #1             ; the whole words between
        MOV  r13, r0
        LSR  r0, #2
        BEQ  .urem
.u4:    LDM  r3, r8-r11
        STM  r2, r8-r11
        ADD  r3, #16
        ADD  r2, #16
        DBNZ r0, .u4
.urem:  MOV  r0, r13
        AND  r0, #3
        BEQ  .ulast
.u1:    MOV  r13, [r3]+
        MOV  [r2]+, r13
        DBNZ r0, .u1
.ulast: MOV  r13, [r3]          ; k = n
        MOV  r14, [r2]
        XOR  r13, r14
        AND  r13, [r1 + 28]
        XOR  r14, r13
        MOV  [r2], r14
.unext: ADD  r4, [r1 + 8]
        ADD  r5, [r1 + 12]
        DEC  r6
        BNE  .urow
        RESTORE r8-r14
.bret:  RET

; a shift: r4 lo, r5 hi, r8 rs, r9 ls, r10 the row, r11 its source, r12
; rows left, r13 n
.shift: MOV  r8, [r1 + 32]
        MOV  r9, [r1 + 36]
        MOV  r10, [r1]
        MOV  r11, [r1 + 4]
        MOV  r12, [r1 + 16]
        MOV  r13, [r1 + 20]
.srow:  MOV  r2, r10
        MOV  r3, r11
        MOV  r4, #0
        MOVS r14, [r1 + 40]     ; pre
        BEQ  .s0
        MOV  r4, [r3]+
.s0:    MOV  r5, #0             ; k = 0: hi, if k < n or last
        TST  r13, r13
        BNE  .s0rd
        MOVS r14, [r1 + 44]
        BEQ  .s0go
.s0rd:  MOV  r5, [r3]+
.s0go:  MOV  r6, r4
        LSR  r6, r8
        MOV  r4, r5
        LSL  r5, r9
        OR   r6, r5
        MOV  r14, [r2]
        XOR  r6, r14
        AND  r6, [r1 + 24]
        XOR  r14, r6
        MOV  [r2]+, r14
        MOVS r0, r13
        BEQ  .snext
        SUB  r0, #1
        BEQ  .slast
.smid:  MOV  r5, [r3]+
        MOV  r6, r4
        LSR  r6, r8
        MOV  r4, r5
        LSL  r5, r9
        OR   r6, r5
        MOV  [r2]+, r6
        DBNZ r0, .smid
.slast: MOV  r5, #0             ; k = n: hi, if last
        MOVS r14, [r1 + 44]
        BEQ  .sl
        MOV  r5, [r3]
.sl:    MOV  r6, r4
        LSR  r6, r8
        LSL  r5, r9
        OR   r6, r5
        MOV  r14, [r2]
        XOR  r6, r14
        AND  r6, [r1 + 28]
        XOR  r14, r6
        MOV  [r2], r14
.snext: ADD  r10, [r1 + 8]
        ADD  r11, [r1 + 12]
        DEC  r12
        BNE  .srow
        RESTORE r8-r14
        RET
