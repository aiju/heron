; The ready queues by hand, as the nucleus has them (nucleus.s's enqueue
; and the first half of schedule), as C functions: enqueue(t),
; dequeue() -> t. The priority field holds the queue number.
        .global _enqueue, _dequeue
        .section .text.sched
_enqueue:
        MOV  r2, [r1 + 20]
        LSL  r2, #2
        ST   r0, [r1]
        MOV  r3, [tail + r2]
        BEQ  .empty
        ST   r1, [r3]
        ST   r1, [tail + r2]
        RET
.empty: ST   r1, [head + r2]
        ST   r1, [tail + r2]
        MOV  r3, [bit_for + r2]
        OR   r3, [bits]
        ST   r3, [bits]
        RET
_dequeue:
        MOV  r2, [bits]
        BEQ  .none
        CLZ  r2, r2
        LSL  r2, #2
        MOV  r1, [head + r2]
        MOV  r3, [r1]
        ST   r3, [head + r2]
        BNE  .left
        ST   r0, [tail + r2]
        MOV  r3, [bit_for + r2]
        MOV  r4, [bits]
        BIC  r4, r3
        ST   r4, [bits]
.left:  RET
.none:  MOV  r1, #0
        RET
        .data
        .align 4
bits:   .word 0
head:   .space 128
tail:   .space 128
bit_for:
        .word 0x80000000, 0x40000000, 0x20000000, 0x10000000
        .word 0x08000000, 0x04000000, 0x02000000, 0x01000000
        .word 0x00800000, 0x00400000, 0x00200000, 0x00100000
        .word 0x00080000, 0x00040000, 0x00020000, 0x00010000
        .word 0x00008000, 0x00004000, 0x00002000, 0x00001000
        .word 0x00000800, 0x00000400, 0x00000200, 0x00000100
        .word 0x00000080, 0x00000040, 0x00000020, 0x00000010
        .word 0x00000008, 0x00000004, 0x00000002, 0x00000001
