; odt: Heron Mini's debug button and ODT, the console in microcode (RFC
; 0045), at chip level and on the model. The program counts in a loop
; with interrupts off until r3 isn't zero; the button, pressed while it
; does, enters ODT on UART 0, and the test's session (hw.py's ODT_SESSION)
; reads and changes r2 and a word of memory, single-steps, sets r3 and
; lets it go on. It then prints r2 and the two words on the suite's
; console, in hex, and halts.
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

CONSOLE  = 0xFFFFFF00

start:  MOV  sp, #0x100000
        DI
        MOV  r2, #0x1234
        CLR  r3
        CLR  r1
.loop:  INC  r1
        TST  r3, r3
        BEQ  .loop
        MOV  r11, #CONSOLE
        MOV  r1, r2
        BSR  hex8
        MOV  r1, [words]
        BSR  hex8
        MOV  r1, [words + 4]
        BSR  hex8
        HALT

; hex8: r1 in hex, eight digits, and a newline. Clobbers r1, r4, r5.
hex8:   MOV  r5, #8
.d:     ROR  r1, #28            ; the top nibble to the bottom
        MOV  r4, r1
        AND  r4, #15
        CMP  r4, #10
        BLO  .n
        ADD  r4, #7
.n:     ADD  r4, #48
        MOV  byte [r11], r4
        DEC  r5
        BNE  .d
        MOV  r4, #10
        MOV  byte [r11], r4
        RET

fatal:  DI
        HALT

        .org 0x1000
words:  .word 0xCAFEF00D
        .word 0x00C0FFEE
