; mandel: ASCII Mandelbrot set, 48 x 20 characters, at most 16 iterations
; per point, in 8.8 fixed point (1.0 = 256). These are exactly the integer
; steps of mandel() in studies/v1_isa/programs/reference.py:
;
;   escape if |x| >= 2.0 or |y| >= 2.0 or xx + yy > 4.0
;   xx = (x*x) >> 8, yy = (y*y) >> 8, xy = (x*y) >> 8 (arithmetic shift)
;   x = xx - yy + cx, y = 2*xy + cy
;
; Each product and its shift is one MULFX, which shifts the 64-bit product
; right arithmetically, as the reference does. |x| and |y| are below 2.0
; whenever they are multiplied, so every value stays far inside 16 bits and
; the reference's 16-bit wrap-around never happens: plain 32-bit arithmetic
; gives the same bits.
;
; The |x| and |y| tests come free with the squares: |x| >= 512 exactly when
; x*x >= 2^18, i.e. xx >= 1024. With xx and yy never negative, the three
; tests together become: escape if xx + yy > 1024, or if xx + yy = 1024 and
; one of the two is the whole 1024 (the other being 0).
;
; Everything lives in registers, so the memory operands have nothing to do
; here. LEA with the indexed mode serves as a three-operand add instead:
; [r10 + r1] is cx + xx, [r11 + r9*2] is cy + 2xy.

        .include "lib/start.s"

W     = 48
H     = 20
MAXIT = 16
X0    = -563                    ; -2.2
XSTEP = 16                      ; 3.0 / 48
YSTEP = 31                      ; 2.4 / 20
Y0    = -295                    ; -(YSTEP * (H - 1)) / 2 rounded down: rows centred on 0
FOUR  = 1024                    ; 4.0

; Registers: r8 = x, r9 = y, r10 = cx, r11 = cy, r12 = iterations - MAXIT
; (counts up to 0), r13 = 4.0; r1-r3 are temporaries.
main:   SAVE r7-r13
        MOV  r13, #FOUR
        MOV  r11, #Y0
.row:   MOV  r10, #X0
.col:   MOV  r8, #0
        MOV  r9, #0
        MOV  r12, #-MAXIT       ; -16 still fits in the instruction
.iter:  MOV  r1, r8
        MULFX r0:r1, r8, #8     ; r1 = xx
        MOV  r2, r9
        MULFX r0:r2, r9, #8     ; r2 = yy
        LEA  r3, [r1 + r2]      ; xx + yy
        CMP  r3, r13
        BHI  .out               ; xx + yy > 4.0
        BEQ  .edge              ; = 4.0: escaped only if |x| or |y| is 2.0
.cont:  MULFX r0:r9, r8, #8     ; y = xy: y's old value isn't needed again
        LEA  r9, [r11 + r9*2]   ; y = cy + 2xy
        LEA  r8, [r10 + r1]
        SUB  r8, r2             ; x = cx + xx - yy
        INC  r12
        BNE  .iter              ; MAXIT iterations without escaping: r12 = 0
.out:   MOV  r1, byte [palette + MAXIT + r12]
        BSR  putc
        SUB  r10, #-XSTEP       ; cx += 16: a one-parcel constant only as -16
        CMP  r10, #X0 + W * XSTEP
        BNE  .col
        BSR  newline
        ADD  r11, #YSTEP
        CMP  r11, #Y0 + H * YSTEP
        BNE  .row
        RESTORE r7-r13
        RET

.edge:  CMP  r1, r13            ; xx = 4.0 (so yy = 0): |x| = 2.0
        BEQ  .out
        CMP  r2, r13            ; yy = 4.0: |y| = 2.0
        BEQ  .out
        BRA  .cont

palette: .ascii " .,,::;;--==++*#@"   ; by iteration count; @ = never escaped
        .align 2

        .include "lib/console.s"
