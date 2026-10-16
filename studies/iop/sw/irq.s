; irq: the IOP interrupts the CPU (RFC 0027, 7.3). The CPU waits in HALT
; with interrupts on; the IOP sets level 3 in the card's interrupt request
; register (cpu-int); the handler clears it, says so through the window,
; and halts with interrupts off.

UART    = 0xFF8C0000            ; device 12 through the window
LSR     = UART + 4 * 5
IRQ_CLR = 0xF0002004            ; the card's interrupt requests: clear (physical 0x7000_2004)

        .org 0x80000000         ; physical 0, in the window
        JMP  start              ; reset
        .org 0x80000048         ; level 3: 0x40 + 4 * 2
        JMP  level3
        .org 0x80000100

start:  MOV  sp, #0x80100000    ; a stack for exceptions, in the window
        EI
.idle:  HALT                    ; until an interrupt
        BRA  .idle

level3: MOV  r1, #4
        MOV  [IRQ_CLR], r1      ; the request first
        LEA  r1, [msg]
.next:  MOV  r2, byte [r1]+
        CMP  r2, #0
        BEQ  .done
.wait:  MOV  r3, [LSR]
        AND  r3, #0x20
        BEQ  .wait
        MOV  [UART], r2
        BRA  .next
.done:  DI
        HALT

msg:    .asciz "Level 3 from the IOP\r\n"
