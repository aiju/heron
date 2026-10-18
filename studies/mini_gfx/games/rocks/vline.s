; The assembly line kernel (vec.h): vec.c's C kernel in draft 2, the same
; pixels. No clipping (the buffer's guard band); each pixel's mask from
; vl_masks; while a line is mostly across, a word's pixels are gathered
; in r0 and put into the word when the line leaves its row or word.
;
;   void vl_line_asm(int x0, int y0, int x1, int y1)
;   void vl_poly_asm(const short *pts, int n, int ox, int oy, int closed)
;
; Both save r7-r14 once and run the same core for each line: a polyline
; of n points costs one call, not n. The core takes the line's ends in
; r1-r4, uses r0-r10, and goes back to vlp_seg for the next line;
; vlp_seg keeps the polyline in r11-r14 (the point, the lines left, the
; offset).
;
; What a line does to its words is patched in by vl_asm_op: the
; gathering starts from 0 and ORs the masks (drawing, XOR) or from -1 and
; ANDs the inverted masks (clearing); it goes into the word with OR, XOR
; or AND. The x shift that finds the word is patched by vl_asm_setup for
; the format. Labels are plain names (vla_...) so the tables of sites
; at the end can name them.

        .global _vl_line_asm, _vl_poly_asm
        .global _vl_site_init, _vl_site_acc, _vl_site_put, _vl_site_shift

        .section .text._vl_line_asm
_vl_line_asm:
        SAVE r7-r14
        MOV  r12, #0            ; no lines after this one
        BRA  vla_core

_vl_poly_asm:
        SAVE r7-r14
        MOV  r11, r1            ; r11: the line's first point
        MOV  r13, r3            ; r13, r14: the offset
        MOV  r14, r4
        MOV  [vlp_first], r1
        MOV  r12, r2            ; r12: lines, n - 1 or n closed
        DEC  r12
        MOV  r0, #0             ; the point past the last: back to the first if closed
        MOVS r5, [sp + 32]      ; closed (the fifth argument, past the saved eight)
        BEQ  vlp_open
        INC  r12
        LEA  r0, [r1 + r2*4]
vlp_open:
        MOV  [vlp_wrap], r0

; the next line, from point r11 to the next (or the first)
vlp_seg:
        TST  r12, r12
        BEQ  vla_ret
        DEC  r12
        MOV  r1, half [r11]
        SXH  r1, r1
        ADD  r1, r13
        MOV  r2, half [r11 + 2]
        SXH  r2, r2
        ADD  r2, r14
        ADD  r11, #4
        MOV  r5, r11
        CMP  r5, [vlp_wrap]
        BNE  vlp_end
        MOV  r5, [vlp_first]
vlp_end:
        MOV  r3, half [r5]
        SXH  r3, r3
        ADD  r3, r13
        MOV  r4, half [r5 + 2]
        SXH  r4, r4
        ADD  r4, r14

; ---- a line from (r1, r2) to (r3, r4) ----
vla_core:
        MOV  r5, r3
        SUB  r5, r1             ; r5: dx
        MOV  r6, r4
        SUB  r6, r2             ; r6: dy
        MOVS r7, r5
        BPL  vla_a1
        NEG  r7, r7             ; r7: |dx|
vla_a1: MOVS r8, r6
        BPL  vla_a2
        NEG  r8, r8             ; r8: |dy|
vla_a2: CMP  r7, r8
        BLO  vla_down

; ---- mostly across: left to right ----
        MOV  r9, #0             ; r9: swapped
        TST  r5, r5
        BPL  vla_x0
        MOV  r1, r3             ; from (x1, y1)
        MOV  r2, r4
        NEG  r6, r6
        MOV  r9, #1
vla_x0: MOV  r10, [_vl_pitchb]  ; r10: the minor step, bytes: a row down
        TST  r6, r6
        BPL  vla_x1
        NEG  r10, r10           ; or up
vla_x1: MOV  r4, r7
        NEG  r4, r4             ; r4: e = -|dx|
        MOV  r5, r8
        ADD  r5, r5             ; r5: inc = 2|dy|
        MOV  r6, r7
        ADD  r6, r6             ; r6: dec = 2|dx|
        INC  r8, r7             ; r8: n = |dx| + 1
        MOVS r0, [_vl_half]
        BEQ  vla_x2
        DEC  r8                 ; the last point left out: if it's
        BRA  vla_x3             ; the first drawn (swapped), a step's skipped
vla_x2: MOV  r9, #0
vla_x3: MOV  r0, [_vl_rows]
        MOV  r2, [r0 + r2*4]    ; the row
        MOV  r0, r1
vla_sh1:
        ASR  r0, #3             ; patched: x >> (pshift - 2)
        AND  r0, #-4
        ADD  r2, r0             ; r2: p, the word
        MOV  r7, [_vl_masks]    ; r7: the masks
        AND  r1, [_vl_ppwm1]
        LEA  r3, [r7 + r1*4]    ; r3: t, the pixel's mask
        MOVS r1, r8             ; r1: n, the pixels left
        BEQ  vlp_seg
        TST  r9, r9
        MOV  r9, [_vl_mend]     ; r9: past the last mask
        BNE  vla_xs

; a word: k pixels, as many as are left in it and the line
vla_xw: MOV  r8, r9
        SUB  r8, r3
        LSR  r8, #2             ; r8: k
        CMP  r8, r1
        BLS  vla_xk
        MOV  r8, r1
vla_xk: SUB  r1, r8             ; r1: the pixels after this word
vla_xa0:
        MOV  r0, #0             ; r0: the word's pixels (patched: #-1)
vla_xl:
vla_xa1:
        OR   r0, [r3]+          ; (patched: AND)
vla_xe: ADD  r4, r5
        BPL  vla_xm
vla_xn: DBNZ r8, vla_xl
vla_xf1:
        OR   r0, [r2]           ; (patched: XOR, AND)
        MOV  [r2]+, r0
        MOV  r3, r7
        TST  r1, r1
        BNE  vla_xw
        BRA  vlp_seg

; the minor step: the pixels so far into the word, a row on
vla_xm:
vla_xf2:
        OR   r0, [r2]           ; (patched)
        MOV  [r2], r0
        ADD  r2, r10
        SUB  r4, r6
vla_xa2:
        MOV  r0, #0             ; (patched)
        BRA  vla_xn

; the first point skipped: as vla_xw, the step taken without its pixel
vla_xs: INC  r1                 ; the skipped point is counted
        MOV  r8, r9
        SUB  r8, r3
        LSR  r8, #2
        CMP  r8, r1
        BLS  vla_xs1
        MOV  r8, r1
vla_xs1:
        SUB  r1, r8
vla_xa3:
        MOV  r0, #0             ; (patched)
        ADD  r3, #4
        BRA  vla_xe

; ---- mostly down: top to bottom ----
vla_down:
        MOV  r9, #0
        TST  r6, r6
        BPL  vla_d0
        MOV  r1, r3             ; from (x1, y1)
        MOV  r2, r4
        NEG  r5, r5             ; dx as drawn: its sign is the direction
        MOV  r9, #1
vla_d0: MOV  r4, r8
        NEG  r4, r4             ; r4: e = -|dy|
        MOV  r6, r8
        ADD  r6, r6             ; r6: dec = 2|dy|
        INC  r8                 ; r8: n = |dy| + 1
        MOVS r0, [_vl_half]
        BEQ  vla_d1
        DEC  r8
        BRA  vla_d2
vla_d1: MOV  r9, #0
vla_d2: MOV  r0, [_vl_rows]
        MOV  r2, [r0 + r2*4]
        MOV  r0, r1
vla_sh2:
        ASR  r0, #3             ; patched
        AND  r0, #-4
        ADD  r2, r0             ; r2: p
        MOV  r0, [_vl_masks]
        AND  r1, [_vl_ppwm1]
        LEA  r3, [r0 + r1*4]    ; r3: t
        MOV  r1, r8             ; r1: n
        MOV  r8, r5             ; r8: dx, for its sign
        MOV  r5, r7
        ADD  r5, r5             ; r5: inc = 2|dx|
        MOV  r7, r0             ; r7: the masks
        MOV  r10, [_vl_pitchb]  ; r10: a row, bytes
        MOV  r0, [r3]           ; r0: the pixel's mask
        TST  r9, r9
        MOV  r9, [_vl_mend]     ; r9: past the last mask
        BNE  vla_ds
        TST  r8, r8
        BMI  vla_dl

; to the right as it goes down
vla_dr: MOV  r8, r0
vla_df1:
        OR   r8, [r2]           ; (patched)
        MOV  [r2], r8
vla_drs:
        ADD  r2, r10
        ADD  r4, r5
        BPL  vla_drm
vla_dr2:
        DBNZ r1, vla_dr
        BRA  vlp_seg
vla_drm:
        SUB  r4, r6
        ADD  r3, #4
        CMP  r3, r9
        BLO  vla_drm1
        MOV  r3, r7
        ADD  r2, #4
vla_drm1:
        MOV  r0, [r3]
        BRA  vla_dr2

; to the left
vla_dl: MOV  r8, r0
vla_df2:
        OR   r8, [r2]           ; (patched)
        MOV  [r2], r8
vla_dls:
        ADD  r2, r10
        ADD  r4, r5
        BPL  vla_dlm
vla_dl2:
        DBNZ r1, vla_dl
        BRA  vlp_seg
vla_dlm:
        SUB  r4, r6
        CMP  r3, r7
        BHI  vla_dlm1
        MOV  r3, r9
        SUB  r2, #4
vla_dlm1:
        SUB  r3, #4
        MOV  r0, [r3]
        BRA  vla_dl2

; the first point skipped: into the loop past its pixel, counted
vla_ds: INC  r1
        TST  r8, r8
        BMI  vla_dls
        BRA  vla_drs

vla_ret:
        RESTORE r7-r14
        RET

        .section .data._vl_sites
        .align 4
vlp_first:
        .word 0                 ; a polyline's first point
vlp_wrap:
        .word 0                 ; the point past its last, if it's closed (else 0)
; the sites vl_asm_op and vl_asm_setup patch
_vl_site_init:
        .word vla_xa0, vla_xa2, vla_xa3, 0
_vl_site_acc:
        .word vla_xa1, 0
_vl_site_put:
        .word vla_xf1, vla_xf2, vla_df1, vla_df2, 0
_vl_site_shift:
        .word vla_sh1, vla_sh2, 0

; vl_clear_box_asm(p, nw, h, pitchb): h rows of nw words (1-16) from p,
; pitchb bytes apart, cleared by stores: a row jumps into an unrolled run
; of CLRs, so it costs a jump, nw stores and the loop.
        .global _vl_clear_box_asm
        .section .text._vl_clear_box_asm
_vl_clear_box_asm:
        TST  r3, r3
        BLE  vcb_done
        LEA  r5, [pc + vcb_s0]
        LSL  r2, #2
        SUB  r5, r2             ; each CLR [r1 + d] is 4 bytes; the last,
        ADD  r5, #4             ; CLR [r1], is 2 and isn't counted
vcb_row:
        JMP  r5
        CLR  [r1 + 60]
        CLR  [r1 + 56]
        CLR  [r1 + 52]
        CLR  [r1 + 48]
        CLR  [r1 + 44]
        CLR  [r1 + 40]
        CLR  [r1 + 36]
        CLR  [r1 + 32]
        CLR  [r1 + 28]
        CLR  [r1 + 24]
        CLR  [r1 + 20]
        CLR  [r1 + 16]
        CLR  [r1 + 12]
        CLR  [r1 + 8]
        CLR  [r1 + 4]
vcb_s0: CLR  [r1]
        ADD  r1, r4
        DEC  r3
        BNE  vcb_row
vcb_done:
        RET
