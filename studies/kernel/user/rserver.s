; The ring server: a console driver with the I/O page mapped, serving the
; ring in the first shared page. It waits for a notify, runs every request
; there is, posts their completions and notifies the client (thread 2).
        .include "sys.inc"
        .org 0
start:  MOV  r12, #UCONSOLE
        MOV  r9, #SHARED
.wait:  SWI  #SYS_WAIT
        MOV  r7, [r9 + RING_SQHEAD]
        MOV  r8, [r9 + RING_CQTAIL]
.next:  CMP  r7, [r9 + RING_SQTAIL]
        BEQ  .done
        MOV  r6, r7
        AND  r6, #RING_MASK
        LSL  r6, #4
        ADD  r6, r9
        MOV  r2, [r6 + RING_SQ + 4]     ; (only writes)
        MOV  r3, [r6 + RING_SQ + 8]
        MOV  r5, r3
        BEQ  .post
.copy:  MOV  r4, byte [r2]+
        ST   r4, byte [r12]
        DEC  r5
        BNE  .copy
.post:  MOV  r5, r8
        AND  r5, #RING_MASK
        LSL  r5, #3
        ADD  r5, r9
        MOV  r4, [r6 + RING_SQ + 12]
        ST   r4, [r5 + RING_CQ]
        ST   r3, [r5 + RING_CQ + 4]
        INC  r8
        INC  r7
        BRA  .next
.done:  ST   r7, [r9 + RING_SQHEAD]
        ST   r8, [r9 + RING_CQTAIL]
        MOV  r1, #2
        MOV  r2, #1
        SWI  #SYS_NOTIFY
        BRA  .wait
