; lines: Bresenham lines, midpoint circles and XOR-filled rectangles in a
; 64x32 1-bit framebuffer (8 bytes per row, bit 7 of a byte is its leftmost
; pixel), printed as 32 rows of '#' and '.', then the number of set pixels.
; The shapes are the tables LINES_STAR, LINES_EXTRA, LINES_CIRCLES and
; LINES_RECTS from programs/reference.py, drawn in the same order.
;
; plot clips each pixel (an unsigned compare catches negative coordinates
; too) and sets the bit in byte fb[y*8 + x/8]. The rectangles are flipped
; a byte at a time, with edge masks from tables.

        .include "lib/start.s"

W       = 64
H       = 32

main:   PUSH r8
        LEA  r8, star           ; r8 walks through all the shape tables
.star:  MVI  r1, 32             ; lines from the centre
        MVI  r2, 16
        LD   r3, [r8]
        LD   r4, [r8 + 4]
        ADDI r8, 8
        BSR  line
        CMP  r8, #extra
        BNE  .star
.extra: LD   r1, [r8]           ; x0, y0, x1, y1
        LD   r2, [r8 + 4]
        LD   r3, [r8 + 8]
        LD   r4, [r8 + 12]
        ADDI r8, 16
        BSR  line
        CMP  r8, #circles
        BNE  .extra
.circ:  LD   r1, [r8]           ; xc, yc, r
        LD   r2, [r8 + 4]
        LD   r3, [r8 + 8]
        ADDI r8, 12
        BSR  circle
        CMP  r8, #rects
        BNE  .circ
.rect:  LD   r1, [r8]           ; x0, y0, x1, y1
        LD   r2, [r8 + 4]
        LD   r3, [r8 + 8]
        LD   r4, [r8 + 12]
        ADDI r8, 16
        BSR  xor_rect
        CMP  r8, #rects_end
        BNE  .rect
        POP  r8
        BRA  show               ; tail call

; plot: set pixel (r1, r2) if it lies inside the framebuffer.
; Clobbers r1-r3 only (line and circle keep values in r4-r7 across it).
plot:   CMP  r1, #W             ; unsigned: negative coordinates are huge
        BHS  .out
        CMP  r2, #H
        BHS  .out
        MOV  r3, r1
        AND  r3, #7
        LDB  r3, [bitmask + r3]
        LSR  r1, #3
        LSL  r2, #3
        ADD  r1, r2             ; r1 = y*8 + x/8
        LDB  r2, [fb + r1]
        OR   r3, r2
        STB  r3, [fb + r1]
.out:   RET

; line: r1 = x0, r2 = y0, r3 = x1, r4 = y1. Bresenham, all octants, exactly
; as in the spec (it stops when (x0, y0) reaches (x1, y1)).
; r8 = x0, r9 = y0, r10 = x1, r11 = y1, r12 = dx, r13 = dy (<= 0),
; r14 = err, r5 = sx, r6 = sy, r4 = e2.
line:   SAVE r8-r14
        MOV  r8, r1
        MOV  r9, r2
        MOV  r10, r3
        MOV  r11, r4
        MOV  r12, r3            ; dx = |x1 - x0|, sx = x0 < x1 ? 1 : -1
        SUB  r12, r1
        BGT  .xpos
        NEG  r12
        MVI  r5, -1
        BRA  .ydir
.xpos:  MVI  r5, 1
.ydir:  MOV  r13, r2            ; dy = -|y1 - y0|, sy = y0 < y1 ? 1 : -1
        SUB  r13, r4
        BLT  .yneg
        NEG  r13
        MVI  r6, -1
        BRA  .err
.yneg:  MVI  r6, 1
.err:   MOV  r14, r12           ; err = dx + dy
        ADD  r14, r13
.loop:  MOV  r1, r8
        MOV  r2, r9
        BSR  plot
        CMP  r8, r10
        BNE  .step
        CMP  r9, r11
        BEQ  .done
.step:  MOV  r4, r14            ; e2 = 2 * err
        ADD  r4, r4
        CMP  r4, r13
        BLT  .noxstep           ; e2 >= dy: step x
        ADD  r14, r13
        ADD  r8, r5
.noxstep:
        CMP  r4, r12
        BGT  .loop              ; e2 <= dx: step y
        ADD  r14, r12
        ADD  r9, r6
        BRA  .loop
.done:  RESTORE r8-r14
        RET

; circle: r1 = xc, r2 = yc, r3 = r. The midpoint circle from the spec:
; x = 0, y = r, d = 3 - 2r; while y >= x: plot the 8 symmetric points,
; then if d > 0 { y--, d += 4(x - y) + 10 } else d += 4x + 6; x++.
; r8 = xc, r9 = yc, r10 = x, r11 = y, r12 = d.
circle: SAVE r8-r12
        MOV  r8, r1
        MOV  r9, r2
        MVI  r10, 0
        MOV  r11, r3
        MVI  r12, 3
        SUB  r12, r3
        SUB  r12, r3
.loop:  CMP  r11, r10
        BLT  .done
        MOV  r4, r10
        MOV  r5, r11
        BSR  plot4              ; (xc +- x, yc +- y)
        MOV  r4, r11
        MOV  r5, r10
        BSR  plot4              ; (xc +- y, yc +- x)
        MOV  r1, r10            ; r1 = x, or x - y
        TST  r12, r12
        BLE  .dsmall
        DEC  r11
        SUB  r1, r11
        LSL  r1, #2
        ADDI r1, 10             ; d += 4 * (x - y) + 10
        BRA  .dnext
.dsmall:
        LSL  r1, #2
        ADDI r1, 6              ; d += 4 * x + 6
.dnext: ADD  r12, r1
        INC  r10
        BRA  .loop
.done:  RESTORE r8-r12
        RET

; plot4: plot (xc + a, yc + b), (xc - a, yc + b), (xc + a, yc - b) and
; (xc - a, yc - b), with r4 = a, r5 = b, r8 = xc, r9 = yc. Clobbers r1-r3.
plot4:  MOV  r1, r8
        ADD  r1, r4
        MOV  r2, r9
        ADD  r2, r5
        BSR  plot
        MOV  r1, r8
        SUB  r1, r4
        MOV  r2, r9
        ADD  r2, r5
        BSR  plot
        MOV  r1, r8
        ADD  r1, r4
        MOV  r2, r9
        SUB  r2, r5
        BSR  plot
        MOV  r1, r8
        SUB  r1, r4
        MOV  r2, r9
        SUB  r2, r5
        BRA  plot               ; tail call

; xor_rect: r1 = x0, r2 = y0, r3 = x1, r4 = y1 (inclusive, and inside the
; framebuffer). Flips each row a byte at a time: the first byte with
; leftmask[x0 & 7], the middle ones completely, the last with
; rightmask[x1 & 7] (both masks at once if the row is a single byte).
xor_rect:
        SAVE r8-r9
        MOV  r5, r1
        AND  r5, #7
        LDB  r5, [leftmask + r5]
        MOV  r6, r3
        AND  r6, #7
        LDB  r6, [rightmask + r6]
        LSR  r1, #3
        LSR  r3, #3
        SUB  r3, r1             ; r3 = bytes after the first one in a row
        BNE  .wide
        AND  r5, r6
.wide:  SUB  r4, r2             ; r4 = rows - 1
        LSL  r2, #3
        ADD  r1, r2
        LEA  r1, [fb + r1]      ; r1 = the first byte of the top row
.row:   MOV  r2, r1
        MOV  r7, r5             ; the first byte's mask
        MOV  r9, r3             ; r9 counts the bytes after the first
        BEQ  .last
.mid:   LDB  r8, [r2]
        XOR  r7, r8
        STB  r7, [r2]
        ADDI r2, 1
        MVI  r7, -1             ; the middle bytes flip completely
        DEC  r9
        BNE  .mid
        MOV  r7, r6             ; the last byte's mask
.last:  LDB  r8, [r2]
        XOR  r7, r8
        STB  r7, [r2]
        ADDI r1, 8
        DEC  r4
        BPL  .row
        RESTORE r8-r9
        RET

; show: print the framebuffer as '#' and '.', then "pixels: N".
; r8 = the next byte, r9 = pixel count, r10 = bytes left in the row,
; r11 = console, r12 = '.', r13 = '#'.
show:   SAVE r8-r13
        LEA  r8, fb
        MVI  r9, 0
        LI   r11, #CONSOLE
        MVI  r12, '.'
        MVI  r13, '#'
.row:   MVI  r10, W / 8
.byte:  LDB  r1, [r8]
        ADDI r8, 1
        LSL  r1, #24            ; pixel 0 (bit 7) to bit 31
        MVI  r2, 8
.bit:   LSL  r1, #1             ; C = the next pixel
        BCS  .set
        STB  r12, [r11]
        DEC  r2
        BNE  .bit
        BRA  .bytedone
.set:   STB  r13, [r11]
        INC  r9
        DEC  r2
        BNE  .bit
.bytedone:
        DEC  r10
        BNE  .byte
        BSR  newline
        CMP  r8, #fb + W * H / 8
        BNE  .row
        LEA  r1, s_pixels
        BSR  puts
        MOV  r1, r9
        BSR  print_u32
        BSR  newline
        RESTORE r8-r13
        RET

        .include "lib/console.s"
        .include "lib/print.s"

; ---- data ----

bitmask:   .byte 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01
leftmask:  .byte 0xFF, 0x7F, 0x3F, 0x1F, 0x0F, 0x07, 0x03, 0x01    ; pixels x&7 .. 7
rightmask: .byte 0x80, 0xC0, 0xE0, 0xF0, 0xF8, 0xFC, 0xFE, 0xFF    ; pixels 0 .. x&7
s_pixels:  .asciz "pixels: "

        .align 4
star:   .word 0, 0,  16, 0,  40, 0,  63, 0,  63, 9          ; (x1, y1) from (32, 16)
        .word 63, 31,  50, 31,  20, 31,  0, 31,  0, 22
extra:  .word -10, 5, 20, 40                                ; (x0, y0, x1, y1)
        .word 70, -3, 45, 12
        .word 5, 3, 5, 3
        .word 60, 28, 2, 28
circles:
        .word 32, 16, 12                                    ; (xc, yc, r)
        .word 10, 10, 6
        .word 56, 24, 9
rects:  .word 40, 2, 60, 12                                 ; (x0, y0, x1, y1)
        .word 2, 20, 20, 29
rects_end:

fb:     .space W * H / 8
