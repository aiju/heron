; The io_uring-style write: r1 batches of b write requests (b = r2 >> 16),
; each of the first (r2 & 0xFFFF) bytes of a line, put in the ring and run
; with one system call. The ring is a demand-zero page.
        .include "sys.inc"
        .org 0
start:  MOV  r8, r1
        MOV  r10, r2
        AND  r10, #0xFFFF       ; length
        MOV  r11, r2
        LSR  r11, #16           ; batch
        MOV  r9, #HEAP          ; the ring
        ST   r0, [r9]           ; (touch it, so it's mapped)
        MOV  r1, r9
        SWI  #SYS_RINGSET
        LEA  r12, [line]
.batch: MOV  r13, r11
        MOV  r7, [r9 + RING_SQTAIL]
.req:   MOV  r6, r7
        AND  r6, #RING_MASK
        LSL  r6, #4
        ADD  r6, r9
        MOV  r1, #OP_WRITE
        ST   r1, [r6 + RING_SQ]
        ST   r12, [r6 + RING_SQ + 4]
        ST   r10, [r6 + RING_SQ + 8]
        ST   r13, [r6 + RING_SQ + 12]
        INC  r7
        DEC  r13
        BNE  .req
        ST   r7, [r9 + RING_SQTAIL]
        SWI  #SYS_RINGENTER
        ; the completions
        MOV  r7, [r9 + RING_CQHEAD]
.cqe:   CMP  r7, [r9 + RING_CQTAIL]
        BEQ  .done
        MOV  r6, r7
        AND  r6, #RING_MASK
        LSL  r6, #3
        ADD  r6, r9
        CMP  r10, [r6 + RING_CQ + 4]
        BNE  .bad
        INC  r7
        BRA  .cqe
.done:  ST   r7, [r9 + RING_CQHEAD]
        DEC  r8
        BNE  .batch
        SWI  #SYS_EXIT
.bad:   MOV  r1, #'X'
        SWI  #SYS_PUTC
        SWI  #SYS_EXIT
        .include "line.inc"
