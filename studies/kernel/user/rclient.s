; The microkernel write through a ring in shared memory: r1 batches of b
; write requests (b = r2 >> 16) of (r2 & 0xFFFF) bytes, put in the ring the
; ring server (thread 1) reads; one notify per batch, and a wait for the
; server's notify when it's done.
        .include "sys.inc"
        .org 0
start:  MOV  r8, r1
        MOV  r10, r2
        AND  r10, #0xFFFF
        MOV  r11, r2
        LSR  r11, #16
        MOV  r9, #SHARED        ; the ring
        ; the line into the second shared page
        LEA  r1, [line]
        MOV  r2, #SHARED + 4096
        MOV  r3, #(line_end - line) / 4
.cp:    MOV  r4, [r1]+
        ST   r4, [r2]+
        DEC  r3
        BNE  .cp
        MOV  r12, #SHARED + 4096
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
        MOV  r1, #1
        MOV  r2, #1
        SWI  #SYS_NOTIFY
.wait:  SWI  #SYS_WAIT
        ; the completions
        MOV  r7, [r9 + RING_CQHEAD]
        MOV  r13, r11
.cqe:   CMP  r7, [r9 + RING_CQTAIL]
        BEQ  .more
        MOV  r6, r7
        AND  r6, #RING_MASK
        LSL  r6, #3
        ADD  r6, r9
        CMP  r10, [r6 + RING_CQ + 4]
        BNE  .bad
        INC  r7
        DEC  r13
        BRA  .cqe
.more:  ST   r7, [r9 + RING_CQHEAD]
        CMP  r13, #0
        BNE  .wait              ; not all done yet
        DEC  r8
        BNE  .batch
        SWI  #SYS_EXIT
.bad:   MOV  r1, #'X'
        SWI  #SYS_PUTC
        SWI  #SYS_EXIT
        .align 4
        .include "line.inc"
