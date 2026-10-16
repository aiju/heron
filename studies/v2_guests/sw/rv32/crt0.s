# C start-up for RV32: the stack at the top of the first megabyte, main,
# then EBREAK, which halts the machine.
        .section .text.start, "ax"
        .globl  _start, exit, abort
_start: li      sp, 0x100000
        call    main
exit:
abort:  ebreak
