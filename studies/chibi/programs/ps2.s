; ps2: the keyboard's bytes to the console. For each: wait for the frame's
; marker (bit 2 of the port's control and status at +4), let the frame's
; parity and stop bits go by (two of the device's clocks, about 160 us),
; then read the byte at +0 and clear the receiver by writing there.
; Chibi Heron's own I/O space (RFC 0047); the suite's console at 0xFFFFFF00.

PS2     = 0xFFFFB000
CONSOLE = 0xFFFFFF00
COUNT   = 2                     ; the bytes the test sends

        .org 0
        MOV  sp, #0x100000
        MOV  r5, #PS2
        MOV  r7, #CONSOLE
        MOV  r6, #COUNT
.next:  MOV  r1, byte [r5 + 4]
        AND  r1, #4
        BEQ  .next
        MOV  r2, #400           ; about 2000 cycles, 320 us
.wait:  DBNZ r2, .wait
        MOV  r1, byte [r5]
        MOV  byte [r5], r1      ; clears the receiver
        MOV  byte [r7], r1
        DBNZ r6, .next
        HALT
