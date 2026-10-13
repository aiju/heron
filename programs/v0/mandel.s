; mandel: ASCII Mandelbrot set, 48 x 20 characters, at most 16 iterations.
;
; 8.8 fixed point (1.0 = 256). 8.8 rather than 4.12 because the product has
; to be shifted right by 8 or 12 and shifts are one bit per instruction:
; >> 8 is a SWAB and a mask, >> 12 would be four more shifts on top.
; |x| and |y| are kept below 2.0, so x*x, y*y < 4.0 and x*x + y*y fits.
;
; Per iteration, exactly:
;   escape if |x| >= 2.0 or |y| >= 2.0 or xx + yy > 4.0
;   xx = (x*x) >> 8, yy = (y*y) >> 8, xy = (x*y) >> 8 (arithmetic shift)
;   x = xx - yy + cx, y = 2*xy + cy

        .include "lib/start.s"

W     = 48
H     = 20
MAXIT = 16
X0    = -563                    ; -2.2
XSTEP = 16                      ; 3.0 / 48
YSTEP = 31                      ; 2.4 / 20
Y0    = -295                    ; rows centred on 0: -(YSTEP * (H - 1)) / 2, rounded down
TWO   = 512
FOUR  = 1024

main:   PUSH r8
        PUSH r9
        PUSH r10
        PUSH r11
        PUSH r12
        PUSH r13
        PUSH r14
        LI   r11, #Y0           ; r11 = cy
        MVI  r1, H
        ST   r1, [rows]
.row:   LI   r10, #X0           ; r10 = cx
        MVI  r1, W
        ST   r1, [cols]
.col:   BSR  point
        LDB  r1, [palette + r1]
        CALL putc
        ADDI r10, XSTEP
        LD   r1, [cols]         ; out of registers: the loop counters live in memory
        DEC  r1
        ST   r1, [cols]
        BNE  .col
        CALL newline
        ADDI r11, YSTEP
        LD   r1, [rows]
        DEC  r1
        ST   r1, [rows]
        BNE  .row
        POP  r14
        POP  r13
        POP  r12
        POP  r11
        POP  r10
        POP  r9
        POP  r8
        RET

; point: c = r10 + i*r11 -> r1 = iterations before z escaped (MAXIT if never).
; Not a normal function: uses r8, r9, r12-r14 without saving them (main
; saves them once instead of 960 times).
point:  MVI  r8, 0              ; r8 = x
        MVI  r9, 0              ; r9 = y
        MVI  r12, 0             ; r12 = iterations
.iter:  MOV  r6, r8             ; r6 = |x|, r7 = |y| (umul16 keeps r6 and r7)
        BPL  .xpos
        NEG  r6
.xpos:  MOV  r7, r9
        BPL  .ypos
        NEG  r7
.ypos:  CMP  r6, #TWO
        BHS  .out
        CMP  r7, #TWO
        BHS  .out
        MOV  r1, r6             ; xx: the squares are unsigned, so skip smul16
        MOV  r2, r6
        CALL umul16
        SWAB r1                 ; r2:r1 >> 8 (x*x < 2^18, so r2 <= 3)
        ZXT  r1
        SWAB r2
        OR   r1, r2
        MOV  r13, r1            ; r13 = xx
        MOV  r1, r7
        MOV  r2, r7
        CALL umul16
        SWAB r1
        ZXT  r1
        SWAB r2
        OR   r1, r2
        MOV  r14, r1            ; r14 = yy
        ADD  r1, r13
        CMP  r1, #FOUR
        BHI  .out
        MOV  r1, r8
        MOV  r2, r9
        CALL smul16             ; x*y, signed
        SWAB r1                 ; bits 23-8 of the product: arithmetic >> 8
        ZXT  r1
        ZXT  r2                 ; (the high half can be FFFF here: mask it)
        SWAB r2
        OR   r1, r2
        SHL  r1                 ; 2xy
        ADD  r1, r11
        MOV  r9, r1             ; y = 2xy + cy
        MOV  r8, r13
        SUB  r8, r14
        ADD  r8, r10            ; x = xx - yy + cx
        INC  r12
        CMPI r12, MAXIT
        BLO  .iter
.out:   MOV  r1, r12
        RET

rows:   .word 0
cols:   .word 0
palette: .ascii " .,,::;;--==++*#@"   ; by iteration count; @ = never escaped

        .include "lib/console.s"
        .include "lib/mul.s"
