; ps2: Heron Mini's PS/2 ports at chip level (board.py's io_space, RFC
; 0041, 22). The keyboard sends three bytes, which are printed in hex as
; they come; then the mouse gets 0xF4 ("enable data reporting"), sent
; bit by bit through the control register, and its answer, 0xFA, is
; printed. The console is the suite's I/O page.
;
; Region 4: +0 the keyboard's byte (read, inverted; a write clears it), +4
; the mouse's, +8 the status (read: bit 0 the keyboard's byte waiting, 1
; the mouse's, 2-3 the keyboard's clock and data, 4-5 the mouse's) and
; the control register (written: bit 0 the keyboard's clock low, 1 its
; data low, 2-3 the mouse's).
;
; Calls write the return address into r7 (RFC 0028, 5.7).

        .org 0x00
        JMP  start
        .org 0x04
        JMP  fatal
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

PS2      = 0xC0000000
CONSOLE  = 0xFFFFFF00

start:  MOV  sp, #0x100000
        DI
        MOV  r10, #PS2
        MOV  r11, #CONSOLE
        ; ---- the keyboard's three bytes ----
        MOV  r9, #3
.kb:    MOV  r1, byte [r10 + 8]
        AND  r1, #1
        BEQ  .kb
        MOV  r1, byte [r10]
        XOR  r1, #0xFF
        CLR  byte [r10]              ; cleared: the keyboard may go on
        BSR  hex
        DEC  r9
        BNE  .kb
        MOV  r1, #10
        MOV  byte [r11], r1

        ; ---- 0xF4 to the mouse ----
        MOV  r1, #4             ; its clock low
        MOV  byte [r10 + 8], r1
        MOV  r2, #400           ; 100 us or more
.w1:    DEC  r2
        BNE  .w1
        MOV  r1, #8             ; its data low (the start bit), the clock released
        MOV  byte [r10 + 8], r1
        MOV  r5, #0x2F4         ; the bits: 0xF4, odd parity 0, the stop bit 1
        MOV  r6, #10
.bit:   BSR  clklow
        MOV  r1, r5
        AND  r1, #1
        XOR  r1, #1
        LSL  r1, #3             ; a 0 pulls the data low
        MOV  byte [r10 + 8], r1
        BSR  clkhigh
        CLR  byte [r10 + 4]          ; the mouse's receiver, which saw it all, cleared
        LSR  r5, #1
        DEC  r6
        BNE  .bit
        BSR  clklow             ; the mouse's acknowledge
        BSR  clkhigh
        CLR  byte [r10 + 4]
        ; ---- its answer ----
.ms:    MOV  r1, byte [r10 + 8]
        AND  r1, #2
        BEQ  .ms
        MOV  r1, byte [r10 + 4]
        XOR  r1, #0xFF
        CLR  byte [r10 + 4]
        BSR  hex
        MOV  r1, #10
        MOV  byte [r11], r1
        HALT

clklow: MOV  r1, byte [r10 + 8]  ; until the mouse's clock is low
        AND  r1, #16
        BNE  clklow
        RET

clkhigh:
        MOV  r1, byte [r10 + 8]
        AND  r1, #16
        BEQ  clkhigh
        RET

; hex: r1's low byte in hex, and a space. Clobbers r2.
hex:    SAVE r7
        MOV  r2, r1
        LSR  r2, #4
        BSR  hexd1
        MOV  r2, r1
        BSR  hexd1
        MOV  r2, #32
        MOV  byte [r11], r2
        RESTORE r7
        RET

hexd1:  AND  r2, #15
        CMP  r2, #10
        BLO  .d
        ADD  r2, #7
.d:     ADD  r2, #48
        MOV  byte [r11], r2
        RET

fatal:  DI
        HALT
