; modes: Heron Mini's video modes and cursor (RFC 0042) for the chip-level
; netlist (studies/mini/video.py has the layout). The mode, the cursor's X
; register and its first line are words at `params`, which the test
; patches. Sixteen rows of pseudo-random words, the mode's line long; the
; descriptors pointing picture line y at row y mod 16 with palette bank
; (y / 16) mod 16; 256 palette colours; the cursor's 32 rows in its two
; tables from line CY. Then the picture, its interrupt and the cursor on,
; and HALT after three frames' interrupts: a whole frame in the mode has
; been sent after the third.
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
        JMP  fatal

BANK1    = 0x00200000
ROWS     = 0x00210000           ; the sixteen rows
ROWW     = 0x00010000 / 4       ; ... as a word address in bank 1
CUR0     = BANK1 + 4 * 2048     ; the cursor's tables
CUR1     = BANK1 + 4 * 3072
VIDEO    = 0xF0000000           ; control; +4 the acknowledge; +16 the cursor's X
PALETTE  = 0xF0000400

start:  MOV  sp, #0x100000
        CALL main
        DI
        HALT

isr:    SAVE r1-r2
        MOV  r2, #VIDEO
        CLR  [r2 + 4]           ; acknowledge
        INC  [frames]
        RESTORE r1-r2
        RTI

fatal:  DI
        HALT

main:   SAVE r7-r12
        ; ---- the mode's table offset, lines and words a line ----
        MOV  r1, [params]       ; the mode
        MOV  r2, #12
        MULU r0:r1, r2
        LEA  r2, [modes]
        ADD  r2, r1
        MOV  r8, [r2]           ; T
        MOV  r9, [r2 + 4]       ; lines
        MOV  r10, [r2 + 8]      ; words a line
        MOV  [tvar], r8
        MOV  [wvar], r10

        ; ---- the rows: row r word j = (j + 1) x 0x9E3779B1 + r x 0x7F4A7C15 ----
        MOV  r11, #ROWS
        CLR  r12                ; r
.rr:    CLR  r3                 ; j
.rj:    MOV  r1, r3
        INC  r1
        MOV  r2, #0x9E3779B1
        MULU r0:r1, r2
        MOV  r4, r1
        MOV  r1, r12
        MOV  r2, #0x7F4A7C15
        MULU r0:r1, r2
        ADD  r4, r1
        MOV  [r11]+, r4
        INC  r3
        CMP  r3, r10
        BLO  .rj
        INC  r12
        CMP  r12, #16
        BLO  .rr

        ; ---- the descriptors: line y, row y mod 16, bank (y / 16) mod 16 ----
        MOV  r11, #BANK1
        MOV  r1, r8
        LSL  r1, #2
        ADD  r11, r1            ; picture line 0's descriptor
        CLR  r12                ; y
.dy:    MOV  r1, r12
        AND  r1, #15
        MULU r0:r1, r10         ; the row's words
        ADD  r1, #ROWW
        MOV  r3, r12
        LSR  r3, #4
        AND  r3, #15
        LSL  r3, #19
        OR   r1, r3
        MOV  [r11]+, r1
        INC  r12
        CMP  r12, r9
        BLO  .dy

        ; ---- the palette: n x 0x04D1 + 0x03A5 ----
        MOV  r11, #PALETTE
        CLR  r12
.pn:    MOV  r1, r12
        MOV  r2, #0x04D1
        MULU r0:r1, r2
        ADD  r1, #0x03A5
        MOV  [r11 + r12*4], r1
        INC  r12
        CMP  r12, #256
        BLO  .pn

        ; ---- the cursor: row k pixel p is (p + k) mod 4, in lines CY.. ----
        MOV  r11, #CUR0
        MOV  r1, [params + 8]   ; CY
        ADD  r1, r8
        LSL  r1, #2
        ADD  r11, r1            ; its first row's word in the first table
        MOV  r9, r11
        ADD  r9, #4096          ; ... in the second, 1024 words on
        CLR  r12                ; k
.ck:    CLR  r4                 ; pixels 0-15
        MOV  r3, #15            ; p, from the top down
.c0:    MOV  r1, r3
        ADD  r1, r12
        AND  r1, #3
        LSL  r4, #2
        OR   r4, r1
        DEC  r3
        BPL  .c0
        MOV  [r11]+, r4
        CLR  r4                 ; pixels 16-31
        MOV  r3, #31
.c1:    MOV  r1, r3
        ADD  r1, r12
        AND  r1, #3
        LSL  r4, #2
        OR   r4, r1
        DEC  r3
        CMP  r3, #16
        BGE  .c1
        MOV  [r9]+, r4
        INC  r12
        CMP  r12, #32
        BLO  .ck

        ; ---- on, and three frames ----
        ; the frame's end has set the interrupt since reset: acknowledged
        ; first
        CLR  [frames]
        MOV  r11, #VIDEO
        MOV  r1, [params + 4]
        MOV  [r11 + 16], r1     ; the cursor's X
        CLR  [r11 + 4]
        MOV  r1, [params]
        LSL  r1, #4
        OR   r1, #0x105         ; the picture, its interrupt, the cursor
        MOV  [r11], r1
        EI
.wait:  MOV  r1, [frames]
        CMP  r1, #3
        BLO  .wait
        RESTORE r7-r12
        RET

        .align 4
params: .word 0                 ; the mode
        .word 100               ; the cursor's X register
        .word 20                ; its first picture line
frames: .word 0
tvar:   .word 0
wvar:   .word 0
modes:  .word 44, 480, 80       ; M0
        .word 44, 480, 80       ; M1
        .word 44, 480, 160      ; M2
        .word 44, 480, 40       ; M3
        .word 44, 480, 20       ; M4
        .word 37, 768, 64       ; M5
        .word 37, 768, 32       ; M6
