; video: Heron Mini's video, for the chip-level netlist (board.py's video,
; studies/mini/video.py has the layout). Sixteen rows of pixels, and the
; 480 lines' descriptors each pointing at one of them, so most of the
; picture is the descriptors' doing:
;
;   row r, word j: pixel k is (j + k + r) mod 16, from a table of the 16
;   words T[n] whose nibble k is (k + n) mod 16
;   line y: row y mod 16, palette bank (y / 16) mod 2; lines 100-131 all
;   row 3, bank 1
;   bank 0 a grey ramp, bank 1 red to blue
;
; Then the picture on and its interrupt, and HALT after three of them: a
; whole frame has been sent after the second.
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

TABLE    = 0x00200000 + 4 * 44  ; picture line 0's descriptor
ROWS     = 0x00202000           ; the sixteen rows, 320 bytes apart
ROWW     = 0x00002000 / 4       ; ... as a word address in bank 1
VIDEO    = 0xF0000000           ; control; +4 the acknowledge
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
        ; ---- T[n]: nibble k is (k + n) mod 16 ----
        LEA  r10, [tab]
        CLR  r8                 ; n
.tn:    CLR  r1                 ; the word
        MOV  r9, #7             ; k, from the top nibble down
.tk:    LSL  r1, #4
        MOV  r2, r9
        ADD  r2, r8
        AND  r2, #15
        OR   r1, r2
        DEC  r9
        BPL  .tk
        MOV  [r10 + r8*4], r1
        INC  r8
        CMP  r8, #16
        BLO  .tn

        ; ---- the rows: row r word j is T[(j + r) mod 16] ----
        MOV  r11, #ROWS
        CLR  r8                 ; r
.rr:    CLR  r9                 ; j
.rj:    MOV  r2, r9
        ADD  r2, r8
        AND  r2, #15
        MOV  r1, [r10 + r2*4]
        MOV  [r11]+, r1
        INC  r9
        CMP  r9, #80
        BLO  .rj
        INC  r8
        CMP  r8, #16
        BLO  .rr

        ; ---- the descriptors ----
        MOV  r11, #TABLE
        CLR  r8                 ; y
.dy:    MOV  r2, r8
        AND  r2, #15            ; row
        MOV  r3, r8
        LSR  r3, #4
        AND  r3, #1             ; bank
        CMP  r8, #100
        BLO  .dset
        CMP  r8, #132
        BHS  .dset
        MOV  r2, #3
        MOV  r3, #1
.dset:  MOV  r1, #80
        MULU r0:r1, r2          ; 80 x row
        ADD  r1, #ROWW
        LSL  r3, #19
        OR   r1, r3
        MOV  [r11]+, r1
        INC  r8
        CMP  r8, #480
        BLO  .dy

        ; ---- the palette: bank 0 grey, bank 1 red to blue ----
        MOV  r11, #PALETTE
        CLR  r8
.pg:    MOV  r1, r8             ; grey: R 2n, G 4n, B 2n
        LSL  r1, #1
        MOV  r2, r1
        LSL  r2, #11
        MOV  r3, r8
        LSL  r3, #7             ; G 4n at bit 5
        OR   r2, r3
        OR   r2, r1
        MOV  [r11 + r8*4], r2
        MOV  r2, #15            ; red to blue: R 2(15 - n), B 2n
        SUB  r2, r8
        LSL  r2, #12
        OR   r2, r1
        MOV  [r11 + 64 + r8*4], r2
        INC  r8
        CMP  r8, #16
        BLO  .pg

        ; ---- on, and three frames ----
        ; the frame's end has set the interrupt since reset (the timing's
        ; counters run into one as they power up): acknowledged first
        CLR  [frames]
        MOV  r11, #VIDEO
        CLR  [r11 + 4]
        MOV  r1, #5             ; the picture and its interrupt on
        MOV  [r11], r1
        EI
.wait:  MOV  r1, [frames]
        CMP  r1, #3
        BLO  .wait
        RESTORE r7-r12
        RET

        .align 4
frames: .word 0
tab:    .space 64
