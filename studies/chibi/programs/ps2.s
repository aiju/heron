; ps2: the keyboard's bytes to the console, received by the device task
; (RFC 0047). For each: wait for the keyboard's interrupt (bit 4 of the
; interrupt controller's status at +0), take the frame the task left at
; 0x70 (the data in its bits 13-6), clear the interrupt (a write of 0 at
; the port's +4) and print the byte. The code is above the words the
; tasks keep at 0x60-0x73.
; Chibi Heron's own I/O space (RFC 0047); the suite's console at 0xFFFFFF00.

PS2     = 0xFFFFB000
IRQC    = 0xFFFFD000
CONSOLE = 0xFFFFFF00
FRAME   = 0x70                  ; the keyboard's last frame
COUNT   = 2                     ; the bytes the test sends

        .org 0
        JMP  start
        .org 0x100
start:  MOV  sp, #0x100000
        MOV  r4, #IRQC
        MOV  r5, #PS2
        MOV  r7, #CONSOLE
        MOV  r6, #COUNT
.next:  MOV  r1, byte [r4]
        AND  r1, #16
        BEQ  .next
        MOV  r1, half [FRAME]
        LSR  r1, #6
        AND  r1, #0xFF
        MOV  r2, #0
        MOV  byte [r5 + 4], r2  ; clears the interrupt
        MOV  byte [r7], r1
        DBNZ r6, .next
        HALT
