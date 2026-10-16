@ A small Thumb program for the guest's lockstep test: shifts, the ALU
@ operations, loads and stores of every size, PUSH and POP, BL; prints "ok".
        .syntax unified
        .thumb
        .globl _start
        .thumb_func
_start: ldr     r0, =0x100000
        mov     sp, r0
        ldr     r0, =1234567
        ldr     r1, =-891
        muls    r1, r0, r1
        lsls    r2, r0, #13
        lsrs    r3, r0, #7
        asrs    r4, r1, #7
        movs    r5, #9
        rors    r4, r5
        adds    r5, r0, r1
        subs    r6, r0, r1
        adcs    r6, r5
        sbcs    r6, r0
        bics    r6, r2
        mvns    r7, r6
        rsbs    r7, r7, #0
        sub     sp, #16
        mov     r7, sp
        str     r1, [sp]
        strh    r1, [r7, #4]
        strb    r1, [r7, #6]
        ldr     r2, [sp]
        ldrh    r3, [r7, #4]
        movs    r5, #4
        ldrsh   r4, [r7, r5]
        ldrb    r5, [r7, #6]
        movs    r6, #6
        ldrsb   r6, [r7, r6]
        add     sp, #16
        push    {r4-r7, lr}
        pop     {r4-r7}
        pop     {r0}
        sxtb    r0, r1
        uxth    r0, r1
        rev     r0, r1
        movs    r0, #0
        movs    r1, #10
1:      adds    r0, r0, r1
        subs    r1, #1
        bne     1b
        cmp     r1, r0
        bhs     2f
        bl      f
        ldr     r1, =0xFFFFFF00
        movs    r0, #'o'
        str     r0, [r1]
        movs    r0, #'k'
        strb    r0, [r1]
        movs    r0, #10
        str     r0, [r1]
2:      bkpt    #0
        .thumb_func
f:      eors    r0, r1
        bx      lr
        .ltorg
