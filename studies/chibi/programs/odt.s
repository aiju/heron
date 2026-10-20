; odt: a program for ODT's test session (hw.py's ODT_KEYS). The halt
; button is held through reset, so ODT is entered before the first
; instruction; the session opens memory and registers, writes some, steps
; through the loop (the flags have to survive ODT) and goes on to HALT.

        .org 0
        MOV  r1, #0x1234
        MOV  r2, #0
.loop:  ADD  r2, #1
        CMP  r2, #3
        BNE  .loop
        MOV  r3, [0x2000]
        MOV  r4, #0x8000000A    ; UART 0's LSR: wait for ODT's last echo to go
.tx:    MOV  r5, byte [r4]
        AND  r5, #0x40
        BEQ  .tx
        HALT

        .org 0x2000
        .word 0xCAFEF00D
