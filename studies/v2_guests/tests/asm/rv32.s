# A small RV32IM program for the guest's lockstep test: the M extension,
# shifts, loads and stores of every size, branches, a call; prints "ok".
        .globl _start
_start: li      sp, 0x100000
        li      t0, 1234567
        li      t1, -891
        mul     t2, t0, t1
        mulh    t3, t0, t1
        mulhu   t4, t0, t1
        mulhsu  t5, t1, t0
        div     a0, t0, t1
        rem     a1, t0, t1
        divu    a2, t1, t0
        remu    a3, t1, t0
        div     a4, t0, zero
        rem     a5, t0, zero
        slli    s0, t0, 13
        srli    s1, t1, 7
        srai    s2, t1, 7
        sll     s3, t0, t1
        srl     s4, t1, t0
        sra     s5, t1, t0
        slt     s6, t1, t0
        sltu    s7, t1, t0
        sltiu   s8, t0, -1
        addi    sp, sp, -16
        sw      t2, 0(sp)
        sh      t1, 4(sp)
        sb      t1, 6(sp)
        lw      s9, 0(sp)
        lh      s10, 4(sp)
        lhu     s11, 4(sp)
        lb      a6, 6(sp)
        lbu     a7, 6(sp)
        auipc   t6, 0x12345
        lui     t6, 0xABCDE
        li      a0, 0
        li      a1, 10
1:      add     a0, a0, a1
        addi    a1, a1, -1
        bnez    a1, 1b
        bltu    a1, a0, 2f
        ebreak
2:      bge     a0, a1, 3f
        ebreak
3:      call    f
        li      t0, 0xFFFFFF00
        li      t1, 'o'
        sw      t1, 0(t0)
        li      t1, 'k'
        sb      t1, 0(t0)
        li      t1, 10
        sw      t1, 0(t0)
        ebreak
f:      xori    a0, a0, 0x55
        ret
