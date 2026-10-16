; ring: the CPU as the kernel's client of the IOP (RFC 0027, 7). It asks
; for its completions at level 3 (OP_NOTIFY) and polls for that one,
; then waits for the host to fill TABLE and set GO, and makes TABLE's
; requests one at a time: each into the kernel's ring in the shared RAM,
; the doorbell rung, and HALT until the completion's interrupt, whose
; handler clears the level, drains the CPU's ring of events and takes the
; completion. Then it halts with interrupts off.

SR      = 0xC0000000            ; the IOP's shared RAM (region 4), in the window
K_IDX   = SR + 0x40             ; +0 our head, +2 the IOP's tail, +4 its completions' head, +6 our tail
K_REQ   = SR + 0x1000
K_CMP   = SR + 0x1400
EVBLK   = SR + 0x1800           ; +0 the IOP's head, +2 our tail
BELL    = 0xF4000000            ; doorbell 0
IRQ_CLR = 0xF0002004            ; the card's interrupt requests: clear
REQS    = 64 * 16 - 1           ; the rings' bytes, less one
CMPS    = 64 * 8 - 1
EVS     = 64 * 2 - 1
OP_NOTIFY = 23

GO      = 0x80001000            ; the host sets it
DONE    = 0x80001004            ; completions taken
STATUS  = 0x80001008            ; their statuses, ORed
RESULT  = 0x8000100C            ; the last one's result
TABLE   = 0x80002000            ; the number of requests, then each as 4 words

        .org 0x80000000         ; physical 0, in the window
        JMP  start
        .org 0x80000048         ; level 3
        JMP  level3
        .org 0x80000100

start:  MOV  sp, #0x80100000
        MOV  r10, #0            ; r10: our head in the ring of requests
        MOV  r11, #0            ; r11: our tail in the ring of completions
        MOV  r12, #0            ; r12: our tail in the ring of events
        CLR  [DONE]
        CLR  [STATUS]
        MOV  r1, #OP_NOTIFY     ; client 0's completions: level 3, CPU 0, not held
        MOV  r2, #0
        MOV  r3, #0x30000
        MOV  r4, #0
        BSR  put
.poll:  MOV  r1, half [K_IDX + 4]
        CMP  r1, r11
        BEQ  .poll
        ADD  r11, #8
        AND  r11, #CMPS
        MOV  half [K_IDX + 6], r11
.go:    MOV  r1, [GO]
        TST  r1, r1
        BEQ  .go
        LEA  r8, [TABLE + 4]
        MOV  r9, [TABLE]
        MOV  r6, #0             ; r6: requests made (r7 is BSR's link)
.next:  MOV  r1, [r8]
        MOV  r2, [r8 + 4]
        MOV  r3, [r8 + 8]
        MOV  r4, [r8 + 12]
        BSR  put
        INC  r6
        ADD  r8, #16
.sleep: DI                      ; until its completion: HALT straight after EI can't miss it
        MOV  r1, [DONE]
        CMP  r1, r6
        BHS  .got
        EI
        HALT
        BRA  .sleep
.got:   DEC  r9
        BNE  .next
        HALT

; put: a request into the ring, r1 (op | flags << 16), r2 (a), r3 (b), r4
; (len | tag << 16), and the doorbell
put:    LEA  r5, [K_REQ]
        ADD  r5, r10
        MOV  [r5], r1
        MOV  [r5 + 4], r2
        MOV  [r5 + 8], r3
        MOV  [r5 + 12], r4
        ADD  r10, #16
        AND  r10, #REQS
        MOV  half [K_IDX], r10
        MOV  [BELL], r10
        RET

level3: SAVE r1-r3
        MOV  r1, #4
        MOV  [IRQ_CLR], r1      ; the level first (RFC 0037, 8)
.ev:    MOV  r1, half [EVBLK]   ; the events: here only ever this ring's
        CMP  r1, r12
        BEQ  .evd
        ADD  r12, #2
        AND  r12, #EVS
        BRA  .ev
.evd:   MOV  half [EVBLK + 2], r12
.cmp:   MOV  r1, half [K_IDX + 4]
        CMP  r1, r11
        BEQ  .out
        LEA  r2, [K_CMP]
        ADD  r2, r11
        MOV  r3, half [r2 + 2]
        MOV  r1, [STATUS]
        OR   r1, r3
        MOV  [STATUS], r1
        MOV  r3, half [r2 + 4]
        MOV  [RESULT], r3
        INC  [DONE]
        ADD  r11, #8
        AND  r11, #CMPS
        BRA  .cmp
.out:   MOV  half [K_IDX + 6], r11
        RESTORE r1-r3
        RTI
