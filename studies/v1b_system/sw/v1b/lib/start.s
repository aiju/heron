; Startup code and vector table for the system (draft 1b on the system bus).
; Include this first; define `main`. main returns -> the console is flushed
; and the machine halts. IRQs are ignored (RTI); traps print "TRAP" and halt.
;
; The console is the I/O card's UART, through lib/uart.s.

        .org 0x00
        JMP  __start            ; reset
        .org 0x04
        RTI                     ; IRQ (unused by default)
        .org 0x08
        JMP  __trap             ; illegal instruction
        .org 0x0C
        JMP  __trap             ; SWI
        .org 0x10
        JMP  __trap             ; divide error
        .org 0x14
        JMP  __trap             ; address error, and bus error
        .org 0x18

__start:
        LI   sp, #0x100000      ; top of the CPU card's RAM
        BSR  __con_init
        CALL main
__exit: DI
        BSR  __con_flush
        HALT

__trap: LEA  r2, [.msg]
.loop:  MOV  r1, byte [r2]+
        BEQ  __exit
        BSR  __con_putc
        BRA  .loop
.msg:   .asciz "TRAP\n"
        .align 2

        .include "uart.s"
