@ C start-up for a Thumb user process under mixed.py's kernel: the stack
@ at the top of the first megabyte (the kernel maps pages there as they
@ are touched), main, then SVC #0, which ends the process.
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
abort:  svc     #0
        b       abort
        .ltorg
