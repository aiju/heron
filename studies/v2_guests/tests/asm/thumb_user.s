@ a Thumb user process for the mixed kernel: a PUSH to an unmapped stack
@ page (the kernel maps it, the PUSH runs again), then "ok" on its console
@ page, and SVC #0
        .syntax unified
        .thumb
        .globl _start
        .thumb_func
_start: movs    r2, #1
        lsls    r2, r2, #20
        mov     sp, r2
        movs    r4, #'o'
        movs    r5, #'k'
        movs    r6, #10
        push    {r4-r6}
        movs    r1, #0xFF
        lsls    r1, r1, #4
        adds    r1, #0xF
        lsls    r1, r1, #12
        pop     {r4-r6}
        strb    r4, [r1]
        strb    r5, [r1]
        strb    r6, [r1]
        svc     #0
