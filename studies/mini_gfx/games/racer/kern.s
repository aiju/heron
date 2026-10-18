; Racer's kernels in draft 2 assembly (racer.h has their C twins and how
; they're picked): the road's spans, a line's copy, a sprite's runs, and
; the projection's steps. The _blk versions use the mini's block
; instructions: FILL for a span's whole words, COPY for a line and a
; sprite's opaque runs, each after MOV rX, #-1; CLZ rX, rX (the count's
; condition latch: see the study's README).
;
; Globals they read: _PS (log2 of a word's pixels), _ppw_mask (its pixels
; - 1), _span_from (the screen format's from[]: the mask of pixels i on).

        .global _spans_asm, _spans_blk, _copy_line_asm, _copy_line_blk
        .global _spr_draw_asm, _spr_draw_blk, _project_asm, _road_line_asm, _road_line_blk

SPITCH_B = 384                  ; a scratch line's pitch in bytes (96 words)

; ---------------------------------------------------------------------
; void spans_asm(unsigned *line, const int *b, const unsigned *cw, int n)
; n spans: span i is pixels b[i] .. b[i + 1] - 1 in colour word cw[i];
; its first and last words merged under their masks, the words between
; stored four a loop (spans_blk: FILL).

        .section .text._spans_asm
_spans_asm:
        SAVE r7-r14
        MOV  r6, r1             ; r6: the line
        MOV  r14, r2            ; r14: the boundaries
        MOV  r13, r3            ; r13: the colours
        MOV  r12, r4            ; r12: spans left
        MOV  r8, [_span_from]   ; r8: from[]
        MOV  r9, [_PS]          ; r9: log2 of a word's pixels
        MOV  r10, [_ppw_mask]   ; r10: its pixels - 1
        MOV  r11, [r14]+        ; r11: the span's first pixel
.span:  MOV  r4, [r14]+         ; r4: the next span's first pixel
        MOV  r2, [r13]+         ; r2: the colour
        CMP  r11, r4
        BGE  .next
        MOV  r1, r11
        LSR  r1, r9
        LEA  r1, [r6 + r1*4]    ; r1: the first word
        MOV  r0, r11
        AND  r0, r10
        MOV  r5, [r8 + r0*4]    ; r5: its mask, from[x0 % ppw]
        MOV  r3, r4
        DEC  r3                 ; the last pixel
        MOV  r0, r3
        AND  r0, r10
        MOV  r7, [r8 + r0*4 + 4]
        NOT  r7                 ; r7: the last word's mask, ~from[x1 % ppw + 1]
        LSR  r3, r9
        MOV  r0, r11
        LSR  r0, r9
        SUB  r3, r0             ; r3: the last word - the first
        BNE  .multi
        AND  r5, r7             ; one word: both masks
        MOV  r0, r5
        MOV  r5, [r1]
        MERGE r5, r2, r0
        MOV  [r1], r5
        BRA  .next
.multi: MOV  r0, r5
        MOV  r5, [r1]
        MERGE r5, r2, r0
        MOV  [r1]+, r5
        DEC  r3                 ; the whole words
        BEQ  .last
        MOV  r0, r3
        LSR  r3, #2
        BEQ  .w1s
.w4:    MOV  [r1]+, r2
        MOV  [r1]+, r2
        MOV  [r1]+, r2
        MOV  [r1]+, r2
        DBNZ r3, .w4
.w1s:   AND  r0, #3
        BEQ  .last
.w1:    MOV  [r1]+, r2
        DBNZ r0, .w1
.last:  MOV  r0, r7
        MOV  r5, [r1]
        MERGE r5, r2, r0
        MOV  [r1], r5
.next:  MOV  r11, r4
        DEC  r12
        BNE  .span
        RESTORE r7-r14
        RET

        .section .text._spans_blk
_spans_blk:
        SAVE r7-r14
        MOV  r6, r1
        MOV  r14, r2
        MOV  r13, r3
        MOV  r12, r4
        MOV  r8, [_span_from]
        MOV  r9, [_PS]
        MOV  r10, [_ppw_mask]
        MOV  r11, [r14]+
.span:  MOV  r4, [r14]+
        MOV  r2, [r13]+
        CMP  r11, r4
        BGE  .next
        MOV  r1, r11
        LSR  r1, r9
        LEA  r1, [r6 + r1*4]
        MOV  r0, r11
        AND  r0, r10
        MOV  r5, [r8 + r0*4]
        MOV  r3, r4
        DEC  r3
        MOV  r0, r3
        AND  r0, r10
        MOV  r7, [r8 + r0*4 + 4]
        NOT  r7
        LSR  r3, r9
        MOV  r0, r11
        LSR  r0, r9
        SUB  r3, r0
        BNE  .multi
        AND  r5, r7
        MOV  r0, r5
        MOV  r5, [r1]
        MERGE r5, r2, r0
        MOV  [r1], r5
        BRA  .next
.multi: MOV  r0, r5
        MOV  r5, [r1]
        MERGE r5, r2, r0
        MOV  [r1]+, r5
        DEC  r3
        BEQ  .last
        MOV  r0, #-1
        CLZ  r0, r0
        .half 0x01FD            ; FILL: r3 words of r2 from r1, r1 past them
.last:  MOV  r0, r7
        MOV  r5, [r1]
        MERGE r5, r2, r0
        MOV  [r1], r5
.next:  MOV  r11, r4
        DEC  r12
        BNE  .span
        RESTORE r7-r14
        RET

; ---------------------------------------------------------------------
; void road_line_asm(unsigned *line, int k, int sx, int stripe): a road
; line drawn, row k's road centred sx pixels from the screen's centre:
; grass over the line, then the rumble strips' span, the road's over
; it, the two lane lines; each span's end words merged under their
; masks, the words between stored (road_line_blk: FILL). More words
; written than exact spans, but four spans' setup instead of nine.
; Globals: _road_rw, _road_rm, _road_ln, _road_l3 (a word a row),
; _road_cw4 (each stripe's grass, rumble, road, lane), _half_w, _W.

        .section .text._road_line_asm
_road_line_asm:
        SAVE r7-r14
        MOV  r6, r1             ; r6: the line
        MOV  r14, r2            ; r14: the row
        MOV  r13, [_half_w]
        ADD  r13, r3            ; r13: the road's centre
        LSL  r4, #4
        LEA  r12, [_road_cw4 + r4*1]    ; r12: the stripe's colours
        MOV  r8, [_span_from]
        MOV  r9, [_PS]
        MOV  r10, [_ppw_mask]
        MOV  r11, [_W]
        MOV  r1, r6             ; the grass
        MOV  r3, [r12]
        MOV  r2, #20
.g:     MOV  [r1]+, r3
        MOV  [r1]+, r3
        MOV  [r1]+, r3
        MOV  [r1]+, r3
        DBNZ r2, .g
        MOV  r5, [_road_rw + r14*4]     ; the rumble strips' span
        ADD  r5, [_road_rm + r14*4]
        MOV  r1, r13
        SUB  r1, r5
        MOV  r2, r13
        ADD  r2, r5
        MOV  r3, [r12 + 4]
        BSR  .paint
        MOV  r5, [_road_rw + r14*4]     ; the road's
        MOV  r1, r13
        SUB  r1, r5
        MOV  r2, r13
        ADD  r2, r5
        MOV  r3, [r12 + 8]
        BSR  .paint
        MOVS r5, [_road_ln + r14*4]     ; the lane lines, if they're a pixel
        BEQ  .done
        LSR  r5, #1
        MOV  r1, r13
        SUB  r1, [_road_l3 + r14*4]
        SUB  r1, r5
        MOV  r2, r1
        ADD  r2, [_road_ln + r14*4]
        MOV  r3, [r12 + 12]
        BSR  .paint
        MOV  r5, [_road_ln + r14*4]
        LSR  r5, #1
        MOV  r1, r13
        ADD  r1, [_road_l3 + r14*4]
        SUB  r1, r5
        MOV  r2, r1
        ADD  r2, [_road_ln + r14*4]
        MOV  r3, [r12 + 12]
        BSR  .paint
.done:  RESTORE r7-r14
        RET

; pixels r1 .. r2 - 1 (clipped to the line) in colour r3; r0-r5 change
.paint: TST  r1, r1
        BPL  .p1
        MOV  r1, #0
.p1:    CMP  r2, r11
        BLE  .p2
        MOV  r2, r11
.p2:    CMP  r1, r2
        BGE  .pret
        MOV  r0, r1
        AND  r0, r10
        MOV  r4, [r8 + r0*4]    ; r4: the first word's mask
        MOV  r0, r2
        DEC  r0
        AND  r0, r10
        MOV  r5, [r8 + r0*4 + 4]
        NOT  r5                 ; r5: the last's
        DEC  r2
        LSR  r2, r9
        LSR  r1, r9
        SUB  r2, r1             ; r2: the last word - the first
        LEA  r1, [r6 + r1*4]
        TST  r2, r2
        BNE  .pm
        AND  r4, r5             ; one word
        MOV  r0, r4
        MOV  r4, [r1]
        MERGE r4, r3, r0
        MOV  [r1], r4
        RET
.pm:    MOV  r0, r4
        MOV  r4, [r1]
        MERGE r4, r3, r0
        MOV  [r1]+, r4
        DEC  r2                 ; the words between
        BEQ  .pl
.pw:    MOV  [r1]+, r3
        DBNZ r2, .pw
.pl:    MOV  r0, r5
        MOV  r4, [r1]
        MERGE r4, r3, r0
        MOV  [r1], r4
.pret:  RET

        .section .text._road_line_blk
_road_line_blk:
        SAVE r7-r14
        MOV  r6, r1
        MOV  r14, r2
        MOV  r13, [_half_w]
        ADD  r13, r3
        LSL  r4, #4
        LEA  r12, [_road_cw4 + r4*1]
        MOV  r8, [_span_from]
        MOV  r9, [_PS]
        MOV  r10, [_ppw_mask]
        MOV  r11, [_W]
        MOV  r1, r6             ; the grass: FILL
        MOV  r2, [r12]
        MOV  r3, #80
        MOV  r0, #-1
        CLZ  r0, r0
        .half 0x01FD
        MOV  r5, [_road_rw + r14*4]
        ADD  r5, [_road_rm + r14*4]
        MOV  r1, r13
        SUB  r1, r5
        MOV  r2, r13
        ADD  r2, r5
        MOV  r3, [r12 + 4]
        BSR  .paint
        MOV  r5, [_road_rw + r14*4]
        MOV  r1, r13
        SUB  r1, r5
        MOV  r2, r13
        ADD  r2, r5
        MOV  r3, [r12 + 8]
        BSR  .paint
        MOVS r5, [_road_ln + r14*4]
        BEQ  .done
        LSR  r5, #1
        MOV  r1, r13
        SUB  r1, [_road_l3 + r14*4]
        SUB  r1, r5
        MOV  r2, r1
        ADD  r2, [_road_ln + r14*4]
        MOV  r3, [r12 + 12]
        BSR  .paint
        MOV  r5, [_road_ln + r14*4]
        LSR  r5, #1
        MOV  r1, r13
        ADD  r1, [_road_l3 + r14*4]
        SUB  r1, r5
        MOV  r2, r1
        ADD  r2, [_road_ln + r14*4]
        MOV  r3, [r12 + 12]
        BSR  .paint
.done:  RESTORE r7-r14
        RET

; as road_line_asm's, the words between by FILL (its value in r2, its
; count in r3: the colour ends up in r2)
.paint: TST  r1, r1
        BPL  .p1
        MOV  r1, #0
.p1:    CMP  r2, r11
        BLE  .p2
        MOV  r2, r11
.p2:    CMP  r1, r2
        BGE  .pret
        MOV  r0, r1
        AND  r0, r10
        MOV  r4, [r8 + r0*4]
        MOV  r0, r2
        DEC  r0
        AND  r0, r10
        MOV  r5, [r8 + r0*4 + 4]
        NOT  r5
        DEC  r2
        LSR  r2, r9
        LSR  r1, r9
        SUB  r2, r1
        LEA  r1, [r6 + r1*4]
        TST  r2, r2
        BNE  .pm
        AND  r4, r5
        MOV  r0, r4
        MOV  r4, [r1]
        MERGE r4, r3, r0
        MOV  [r1], r4
        RET
.pm:    MOV  r0, r4
        MOV  r4, [r1]
        MERGE r4, r3, r0
        MOV  [r1]+, r4
        MOV  r0, r2
        MOV  r2, r3             ; r2: the colour
        MOV  r3, r0
        DEC  r3                 ; r3: the words between
        BEQ  .pl
        MOV  r0, #-1
        CLZ  r0, r0
        .half 0x01FD            ; FILL: r3 words of r2 from r1, r1 past them
.pl:    MOV  r0, r5
        MOV  r4, [r1]
        MERGE r4, r2, r0
        MOV  [r1], r4
.pret:  RET

; ---------------------------------------------------------------------
; void copy_line_asm(unsigned *d, const unsigned *s): a line's 80 words

        .section .text._copy_line_asm
_copy_line_asm:
        MOV  r3, #10
.l:     MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        MOV  r0, [r2]+
        MOV  [r1]+, r0
        DEC  r3
        BNE  .l
        RET

        .section .text._copy_line_blk
_copy_line_blk:
        MOV  r3, #80
        MOV  r0, #-1
        CLZ  r0, r0
        .half 0x02FD            ; COPY: r3 words from r2 to r1
        RET

; ---------------------------------------------------------------------
; void spr_draw_asm(unsigned *d, const unsigned *img, int r0, int n)
; rows r0 .. r0 + n - 1 of a sprite's image (sprites.c: h row addresses,
; each row a list of runs ended by 0: a header, opaque << 31 | words << 16
; | the first word's byte offset, then the words, opaque ones to store,
; mixed ones a keep mask and the colours), each row SPITCH words below
; the last.

        .section .text._spr_draw_asm
_spr_draw_asm:
        SAVE r8-r14
        MOV  r14, r1            ; r14: the row's first word
        MOV  r13, r2            ; r13: the image
        MOV  r12, r3            ; r12: the image's row
        MOVS r11, r4            ; r11: rows left
        BLE  .done
.row:   MOV  r2, [r13 + r12*4]  ; r2: the row's runs
.run:   MOVS r5, [r2]+          ; the header: 0 the end, negative opaque
        BEQ  .rnext
        BMI  .opq
        ZXH  r1, r5
        ADD  r1, r14            ; r1: where it starts
        SWAP r3, r5
        ZXH  r3, r3             ; r3: its words
.mixed: MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .mixed
        BRA  .run
.opq:   ZXH  r1, r5
        ADD  r1, r14
        SWAP r3, r5
        AND  r3, #0x7FFF
.o1:    MOV  r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .o1
        BRA  .run
.rnext: ADD  r14, #SPITCH_B
        INC  r12
        DEC  r11
        BNE  .row
.done:  RESTORE r8-r14
        RET

; the same with COPY for the opaque runs (3 words or more: sprites.c's
; encoding makes shorter ones mixed)
        .section .text._spr_draw_blk
_spr_draw_blk:
        SAVE r8-r14
        MOV  r14, r1
        MOV  r13, r2
        MOV  r12, r3
        MOVS r11, r4
        BLE  .done
.row:   MOV  r2, [r13 + r12*4]
.run:   MOVS r5, [r2]+
        BEQ  .rnext
        BMI  .opq
        ZXH  r1, r5
        ADD  r1, r14
        SWAP r3, r5
        ZXH  r3, r3
.mixed: MOV  r0, [r1]
        AND  r0, [r2]+
        OR   r0, [r2]+
        MOV  [r1]+, r0
        DBNZ r3, .mixed
        BRA  .run
.opq:   ZXH  r1, r5
        ADD  r1, r14
        SWAP r3, r5
        AND  r3, #0x7FFF
        MOV  r0, #-1
        CLZ  r0, r0
        .half 0x02FD            ; COPY: r3 words from r2 to r1, both past them
        BRA  .run
.rnext: ADD  r14, #SPITCH_B
        INC  r12
        DEC  r11
        BNE  .row
.done:  RESTORE r8-r14
        RET

; ---------------------------------------------------------------------
; int project_asm(unsigned *desc): track.c's projection loop (its C is the
; reference), with proj_setup's constants: for d = 256 down to 6, the
; road at z = camz + zt[d]: its screen x (one multiply), its line (one
; more, but on the flat), its stripe; a step above the lines filled so
; far fills them down to there with its row's descriptor. Returns the top
; line filled.

        .section .text._project_asm
_project_asm:
        SAVE r7-r14
        MOV  r14, r1            ; r14: the descriptors
        MOV  r13, #256          ; r13: d
        MOV  r12, #480          ; r12: the top line filled so far
        MOV  r11, [_camz]
        MOV  r10, [_proj_q]
        MOV  r9, [_proj_k]
        MOV  r8, [_proj_hcam]
        ADD  r8, #1024          ; r8: CAM_H + the camera's height
.step:  MOV  r1, [_zt + r13*4]
        ADD  r1, r11            ; r1: z
        MOV  r2, r1
        LSR  r2, #5             ; r2: the track's entry
        CMP  r2, #4096
        BHS  .wrap
        MOV  r3, [_trk_pos + r2*4]
        BRA  .gotp
.wrap:  SUB  r2, #4096          ; past the lap's end: the next lap's
        MOV  r3, [_trk_pos + r2*4]
        ADD  r3, [_drift]
.gotp:  SUB  r3, r10            ; (P - Q) / 16
        BMI  .neg               ; |diff| * d: MULU's 16-bit path (MULS
        CMP  r3, #32767         ; takes 32 steps for a negative operand)
        BLS  .c1
        MOV  r3, #32767
.c1:    MULU r0:r3, r13
        ASR  r3, #6
        BRA  .gx
.neg:   NEG  r3
        CMP  r3, #32767
        BLS  .c2
        MOV  r3, #32767
.c2:    MULU r0:r3, r13
        NEG  r3
        ASR  r3, #6             ; as C's (diff * d) >> 6, rounding down
.gx:    SUB  r3, r9             ; the centre, 640-unit pixels
        MOV  r0, [_XS]
        ASR  r3, r0             ; r3: sx, the mode's pixels
        MOV  r4, half [_trk_height + r2*2]
        SXH  r4, r4
        MOV  r5, r8
        SUB  r5, r4             ; the camera over the road there
        CMP  r5, #1024
        BEQ  .flat
        TST  r5, r5
        BMI  .over
        MULU r0:r5, r13
        ASR  r5, #10
        BRA  .gy
.over:  MULS r0:r5, r13         ; the road above the camera
        ASR  r5, #10
        BRA  .gy
.flat:  MOV  r5, r13
.gy:    ADD  r5, #223           ; r5: the line, HY - 1 + d * hh / CAM_H
        LSR  r1, #4
        AND  r1, #16            ; r1: the stripe, << 4
        MOV  half [_step_sx + r13*2], r3
        MOV  r0, r12
        SWAP r0, r0
        ZXH  r4, r5
        OR   r0, r4
        MOV  [_step_yc + r13*4], r0     ; the line, and the nearer road's top
        CMP  r5, r12
        BGE  .nstep             ; behind a crest
        CMP  r5, #20
        BGE  .y1
        MOV  r5, #20            ; not over the HUD
.y1:    MOV  r7, r13
        DEC  r7                 ; r7: the row, d - 1
        ; the descriptor: the centre clamped to the row's limit, the
        ; window's left pixel ws, its phase's copy, its word, the stripe
        MOV  r6, [_road_lim + r7*4]
        MOV  r4, r3
        CMP  r4, r6
        BLE  .l1
        MOV  r4, r6
.l1:    NEG  r6
        CMP  r4, r6
        BGE  .l2
        MOV  r4, r6
.l2:    MOV  r0, [_road_ws0]
        SUB  r0, r4             ; r0: ws
        MOV  r4, r0
        AND  r4, [_ppw_mask]
        MOV  r6, [_road_phw + r4*4]
        MOV  r4, [_PS]
        ASR  r0, r4
        ADD  r6, r0
        ADD  r6, [_road_rowbase + r7*4]
        ADD  r6, [_road_stripe + r1*1]
        MOV  r2, r5             ; r2: the new top
        MOV  r4, r3             ; r4: the line's information, sx << 16 |
        SWAP r4, r4             ; row << 8 | stripe << 4 | LK_ROAD
        AND  r4, #-65536
        OR   r4, [_kinfo + r13*4]
        OR   r4, r1
.fill:  MOV  [r14 + r5*4], r6
        MOV  [_line_info + r5*4], r4
        INC  r5
        CMP  r5, r12
        BLT  .fill
        MOV  r12, r2
.nstep: DEC  r13
        CMP  r13, #6
        BGE  .step
        MOV  r1, r12
        RESTORE r7-r14
        RET
