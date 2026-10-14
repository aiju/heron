; line_run(job): the inner loop of a line, in draft 1b (src/line.c has
; the C version and src/gfx.h the job: n pixels from byte p, mask m; each
; is v = (v & ~(m & ka)) ^ (m & kx); e decides the minor steps).
;
; LineJob: p 0, m 4, ka 8, kx 12, n 16, e 20, inc 24, dec 28, ystep 32,
;          dir 36, depth 40
;
; At 8 bits per pixel with COPY a pixel is a byte store. Otherwise the
; pixel's mask moves through the byte: left by bpp for a step right,
; and when it leaves the byte (its low byte is then 0: ZXB) it comes back
; at the bottom of the next one.
;
; r2 p, r3 m, r4 n, r5 e, r6 ka, r7 kx, r8 inc, r9 dec, r10 ystep,
; r11 dir (or 8 - bpp), r12/r13 the byte, r14 bpp

        .global _line_run
        .section .text._line_run
_line_run:
        SAVE r8-r14
        MOV  r2, [r1]
        MOV  r3, [r1 + 4]
        MOV  r6, [r1 + 8]
        MOV  r7, [r1 + 12]
        MOV  r5, [r1 + 20]
        MOV  r8, [r1 + 24]
        MOV  r9, [r1 + 28]
        MOV  r10, [r1 + 32]
        MOV  r11, [r1 + 36]
        MOV  r12, [r1 + 40]
        MOV  r4, [r1 + 16]
        BLE  .done
        CMP  r12, #3
        BNE  .gen
        CMP  r6, #-1
        BNE  .gen
        TST  r11, r11
        BNE  .yb
.xb:    ST   r7, byte [r2]+     ; 8 bits, COPY, x-major
        CMP  r5, #0
        BLE  .xb1
        ADD  r2, r10
        SUB  r5, r9
.xb1:   ADD  r5, r8
        DEC  r4
        BNE  .xb
.done:  RESTORE r8-r14
        RET
.yb:    ST   r7, byte [r2]      ; 8 bits, COPY, y-major
        ADD  r2, r10
        CMP  r5, #0
        BLE  .yb1
        ADD  r2, r11
        SUB  r5, r9
.yb1:   ADD  r5, r8
        DEC  r4
        BNE  .yb
        BRA  .done

.gen:   MOV  r14, #1
        LSL  r14, r12           ; bpp
        TST  r11, r11
        BEQ  .xg
        BMI  .yl
.yr:    MOV  r12, byte [r2]     ; y-major, x going right
        MOV  r13, r3
        AND  r13, r6
        BIC  r12, r13
        MOV  r13, r3
        AND  r13, r7
        XOR  r12, r13
        ST   r12, byte [r2]
        ADD  r2, r10
        CMP  r5, #0
        BLE  .yr2
        LSL  r3, r14
        ZXB  r13, r3
        BNE  .yr1
        LSR  r3, #8
        INC  r2
.yr1:   SUB  r5, r9
.yr2:   ADD  r5, r8
        DEC  r4
        BNE  .yr
        BRA  .done

.yl:    MOV  r11, #8            ; y-major, x going left
        SUB  r11, r14
.ylp:   MOV  r12, byte [r2]
        MOV  r13, r3
        AND  r13, r6
        BIC  r12, r13
        MOV  r13, r3
        AND  r13, r7
        XOR  r12, r13
        ST   r12, byte [r2]
        ADD  r2, r10
        CMP  r5, #0
        BLE  .yl2
        MOV  r13, r3
        LSR  r3, r14
        BNE  .yl1
        LSL  r13, r11           ; off the bottom: the top of the byte before
        MOV  r3, r13
        DEC  r2
.yl1:   SUB  r5, r9
.yl2:   ADD  r5, r8
        DEC  r4
        BNE  .ylp
        BRA  .done

.xg:    MOV  r12, byte [r2]     ; x-major, going right
        MOV  r13, r3
        AND  r13, r6
        BIC  r12, r13
        MOV  r13, r3
        AND  r13, r7
        XOR  r12, r13
        ST   r12, byte [r2]
        LSL  r3, r14
        ZXB  r13, r3
        BNE  .xg1
        LSR  r3, #8
        INC  r2
.xg1:   CMP  r5, #0
        BLE  .xg2
        ADD  r2, r10
        SUB  r5, r9
.xg2:   ADD  r5, r8
        DEC  r4
        BNE  .xg
        BRA  .done
