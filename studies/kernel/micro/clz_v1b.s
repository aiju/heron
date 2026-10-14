; clz(x) for C (sched.c): the one instruction, as a function.
        .global k_clz
        .section .text.k_clz
k_clz:  CLZ  r1, r1
        RET
