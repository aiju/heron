; ring: the CPU as the kernel's client of the IOP (RFC 0027, 7; RFC 0040,
; 5). It asks for its completion ring and its ring of events, both in its
; own RAM, and polls for those requests' completions; then it routes its
; completions' event (SRC_RING + 0) to level 3, slow, and polls for that
; one. Then it waits for the host to fill TABLE and set GO, and makes
; TABLE's requests one at a time: each into the kernel's ring in the
; shared RAM, the doorbell rung, and HALT until its event's interrupt,
; whose handler clears the level, drains the ring of events, says it has
; handled them (the completion ring's RING_EVENTS copied to the request
; ring's) and takes the completions. Then it halts with interrupts off.

SR      = 0xC0000000            ; the IOP's shared RAM (region 4), in the window
K_REQ   = SR + 0x1000           ; the kernel's request ring: +0 our head, +2 the events
                                ; we've handled, +4 the IOP's tail, from +8 64 requests
CMP     = 0x80003000            ; our completion ring, physical 0x3000: +0 the IOP's
                                ; head, +2 events it's posted, +4 our tail, from +8 64
                                ; completions
EVR     = 0x80003400            ; our ring of events, physical 0x3400: likewise, 64 halfwords
WAKE    = SR + 0x3800           ; its wake-me word
SETS    = SR + 0x3810           ; OP_EVRING's settings
BELL    = 0xF4000000            ; doorbell 0
IRQ_CLR = 0xF0002004            ; the card's request register: clear
N       = 64 - 1                ; each ring's entries, less one
OP_ROUTE = 19
OP_EVRING = 21
OP_CMPRING = 23
SRC_RING = 32
SLOW    = 1

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
        MOV  r10, #0            ; r10: requests made, our head
        MOV  r11, #0            ; r11: completions taken, our tail
        MOV  r12, #0            ; r12: events taken
        CLR  [DONE]
        CLR  [STATUS]
        CLR  [K_REQ]            ; our head, and the events handled
        MOV  r1, #OP_CMPRING    ; our completion ring: 64 at physical 0x3000
        MOV  r2, #0x3000
        MOV  r3, #0
        MOV  r4, #64
        BSR  put
        BSR  poll
        MOV  r1, #0x3400        ; our ring of events: 64 at 0x3400, the wake-me word
        MOV  [SETS], r1
        MOV  r1, #(64 | (WAKE & 0xFFFF) << 16)
        MOV  [SETS + 4], r1
        MOV  r1, #0x4000
        MOV  [SETS + 8], r1
        CLR  [WAKE]
        MOV  r1, #OP_EVRING
        MOV  r2, #(SETS - 0x80000000)
        MOV  r3, #0             ; CPU 0
        MOV  r4, #0
        BSR  put
        BSR  poll
        MOV  r1, #(OP_ROUTE | SLOW << 16)  ; our completions' event: level 3 on CPU 0, slow, not held
        MOV  r2, #0
        MOV  r3, #(SRC_RING | 3 << 16)
        MOV  r4, #0
        BSR  put
        BSR  poll
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
put:    PUSH r1
        MOV  r5, r10
        AND  r5, #N
        LSL  r5, #4
        LEA  r1, [K_REQ + 8]    ; (r1 after: it's the op)
        ADD  r5, r1
        POP  r1
        MOV  [r5], r1
        MOV  [r5 + 4], r2
        MOV  [r5 + 8], r3
        MOV  [r5 + 12], r4
        INC  r10
        MOV  half [K_REQ], r10
        MOV  [BELL], r10
        RET

; poll: until a completion, taken and dropped
poll:   MOV  r1, half [CMP]
        CMP  r1, r11
        BEQ  poll
        INC  r11
        MOV  half [CMP + 4], r11
        RET

level3: SAVE r1-r3
        MOV  r1, #4
        MOV  [IRQ_CLR], r1      ; the level first (RFC 0040, 5.1)
.ev:    MOV  r1, half [EVR]     ; the events: here only ever our completions'
        CMP  r1, r12
        BEQ  .evd
        INC  r12
        BRA  .ev
.evd:   MOV  half [EVR + 4], r12
        MOV  r1, half [CMP + 2]     ; handled, then the completions looked at
        MOV  half [K_REQ + 2], r1
.cmp:   MOV  r1, half [CMP]
        CMP  r1, r11
        BEQ  .out
        MOV  r2, r11
        AND  r2, #N
        LSL  r2, #3
        ADD  r2, #(CMP + 8)
        MOV  r3, half [r2 + 2]
        MOV  r1, [STATUS]
        OR   r1, r3
        MOV  [STATUS], r1
        MOV  r3, half [r2 + 4]
        MOV  [RESULT], r3
        INC  [DONE]
        INC  r11
        BRA  .cmp
.out:   MOV  half [CMP + 4], r11
        RESTORE r1-r3
        RTI
