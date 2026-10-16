; hello: the CPU's first program, which the IOP boots (RFC 0027, 8.2). It
; runs from the reset vector, physical 0, in the supervisor's window. It
; writes a line to the console through the I/O bus's window, leaves a word
; in the IOP's shared RAM, rings doorbell 5 (a client with no rings, so
; the IOP's Forth sees it in BELLS), and halts.

UART   = 0xFF8C0000             ; device 12 through the window: register r at +4r
LSR    = UART + 4 * 5
SHARED = 0xC0000000             ; region 4, the IOP's shared RAM
BELL   = 0xF4000014             ; the IOP's doorbell 5

        .org 0x80000000         ; physical 0, in the window
start:  LEA  r1, [msg]
.next:  MOV  r2, byte [r1]+
        CMP  r2, #0
        BEQ  .done
.wait:  MOV  r3, [LSR]
        AND  r3, #0x20
        BEQ  .wait
        MOV  [UART], r2
        BRA  .next
.done:  MOV  r2, #0x1234
        MOV  [SHARED + 0x200], r2
        MOV  [BELL], r2
        HALT

msg:    .asciz "Hello from the CPU\r\n"
