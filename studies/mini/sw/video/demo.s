; demo: RFC 0042's video options from a program, for the simulator
; (heron mini sim): 1024 x 768 at 2 bits a pixel (M5) from a frame base
; (D1), bars in four colours, a cursor (C1) over them, and the beam's
; position (P1) read as each frame's interrupt is taken. After two frames
; it prints the line and the character it last read, and halts.
;
; The frame is 768 lines of 64 words from bank 1's word FBW. A word's
; pixels are linear (pixel p is bits 2p and 2p + 1), so a word of 16
; pixels all of colour c is c's entry in `solid`. Pixel (x, y) has colour
; (x/64 + y/64) mod 4. The cursor's rows are in its two tables, line y's
; at words 2048 + T + y and 3072 + T + y of bank 1 (T = 37 in XGA).
;
; Calls write the return address into r7 (RFC 0028, 5.7).

        .org 0x00
        JMP  start              ; reset
        .org 0x04
        JMP  isr                ; IRQ
        .org 0x08
        JMP  fatal
        .org 0x0C
        JMP  fatal
        .org 0x10
        JMP  fatal
        .org 0x14
        JMP  fatal
        .org 0x18
        JMP  fatal
        .org 0x1C

VIDEO    = 0xF0000000           ; +0 control, +4 acknowledge, +8 the beam,
                                ; +C the frame base, +10 the cursor's X
PALETTE  = 0xF0000400
CONSOLE  = 0xFFFFFF00
FB       = 0x00210000           ; the frame: bank 1's word 0x4000
FBW      = 0x4000
T        = 37                   ; XGA's tables: line y's word is T + y
CT0      = 0x00200000 + 4 * (2048 + T + 300)    ; the cursor's rows at line 300
CT1      = 0x00200000 + 4 * (3072 + T + 300)
CX       = 500 - 4              ; its X: the beam 4 pixels before x = 500
CTRL     = 0x355                ; on, the interrupt on, M5, the cursor on, D1

start:  MOV  sp, #0x100000

        ; ---- the palette: black, red, green, blue; the cursor's 253-255
        ; white, black, yellow
        MOV  r11, #PALETTE
        CLR  [r11]
        MOV  r1, #0xF800
        MOV  [r11 + 4], r1
        MOV  r1, #0x07E0
        MOV  [r11 + 8], r1
        MOV  r1, #0x001F
        MOV  [r11 + 12], r1
        MOV  r1, #0xFFFF
        MOV  [r11 + 4 * 253], r1
        CLR  [r11 + 4 * 254]
        MOV  r1, #0xFFE0
        MOV  [r11 + 4 * 255], r1

        ; ---- the frame
        LEA  r10, [solid]
        MOV  r11, #FB
        CLR  r8                 ; y
.y:     CLR  r9                 ; j, the word
.j:     MOV  r2, r9
        LSR  r2, #2             ; x / 64
        MOV  r3, r8
        LSR  r3, #6             ; y / 64
        ADD  r2, r3
        AND  r2, #3
        MOV  r1, [r10 + r2*4]
        MOV  [r11]+, r1
        INC  r9
        CMP  r9, #64
        BLO  .j
        INC  r8
        CMP  r8, #768
        BLO  .y

        ; ---- the cursor: a box in lines 300-331, yellow along the top
        ; and bottom, white down the sides (pixel p is bits 2p, 2p + 1 of
        ; a row's two words, one in each table)
        MOV  r11, #CT0
        MOV  r12, #CT1
        MOV  r1, #-1
        MOV  [r11], r1
        MOV  [r12], r1
        MOV  [r11 + 124], r1
        MOV  [r12 + 124], r1
        ADD  r11, #4
        ADD  r12, #4
        MOV  r8, #30
        MOV  r1, #1             ; pixel 0: colour 1
        MOV  r2, #0x40000000    ; pixel 31
.c:     MOV  [r11]+, r1
        MOV  [r12]+, r2
        DEC  r8
        BNE  .c

        ; ---- the registers; the mode from the next frame. The frames
        ; drawing took have left the interrupt set: acknowledged first, the
        ; second interrupt is the end of the first 1024 x 768 frame
        MOV  r11, #VIDEO
        MOV  r1, #FBW           ; the frame base, palette bank 0
        MOV  [r11 + 12], r1
        MOV  r1, #CX
        MOV  [r11 + 16], r1
        CLR  [frames]
        CLR  [r11 + 4]
        MOV  r1, #CTRL
        MOV  [r11], r1
        EI
.wait:  MOV  r1, [frames]
        CMP  r1, #2
        BLO  .wait
        DI

        ; ---- the beam as the last interrupt was taken
        MOV  r1, [beam]
        AND  r1, #0x3FF
        MOV  r2, #3
        CALL hex
        MOV  r1, #' '
        MOV  byte [CONSOLE], r1
        MOV  r1, [beam]
        LSR  r1, #16
        MOV  r2, #2
        CALL hex
        MOV  r1, #10
        MOV  byte [CONSOLE], r1
        HALT

isr:    SAVE r1-r2
        MOV  r2, #VIDEO
        MOV  r1, [r2 + 8]       ; the beam
        MOV  [beam], r1
        CLR  [r2 + 4]           ; acknowledge
        INC  [frames]
        RESTORE r1-r2
        RTI

fatal:  DI
        HALT

; the low r2 hex digits of r1
hex:    MOV  r3, r2
        LSL  r3, #2
.h:     SUB  r3, #4
        MOV  r4, r1
        LSR  r4, r3
        AND  r4, #15
        CMP  r4, #10
        BLO  .d
        ADD  r4, #'A' - '0' - 10
.d:     ADD  r4, #'0'
        MOV  byte [CONSOLE], r4
        TST  r3, r3
        BNE  .h
        RET

        .align 4
solid:  .word 0, 0x55555555, 0xAAAAAAAA, 0xFFFFFFFF
frames: .word 0
beam:   .word 0
