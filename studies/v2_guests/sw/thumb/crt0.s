@ C start-up for Thumb: the stack at the top of the first megabyte, main,
@ then BKPT, which halts the machine.
        .syntax unified
        .thumb
        .section .text.start, "ax"
        .globl  _start, exit, abort
        .thumb_func
_start: ldr     r0, =0x100000
        mov     sp, r0
        bl      main
        .thumb_func
exit:
        .thumb_func
abort:  bkpt    #0
        .ltorg
