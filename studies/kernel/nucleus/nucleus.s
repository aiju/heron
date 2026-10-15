; The benchmark nucleus: a small message-passing kernel for v1bs
; (report 0020's appendix), written to measure what an operating system's hot paths
; cost on draft 1b and what the system extensions save. It is not an
; operating system: there is no file system, no loader, no allocator for
; user memory beyond demand-zero pages, and processes come from a table
; the build fills in (build.py).
;
; Variants (build.py's features), one of:
;   none   no register banks: only sp is banked by the mode, so the
;          nucleus saves and restores the user's registers itself
;   half   r8-r15 banked: the nucleus has its own r8-r15, each thread its
;          own r8-r15 in its bank; r1-r7 and HI are shared, so messages in
;          r1-r5 pass between threads untouched
;   full   r1-r15 and HI banked: the nucleus has a whole bank to itself
; and optionally
;   softtlb  the map is a cache: every process has a page table in memory,
;          and a page fault on a page the table has is a refill
;
; The design is L4's and QNX's: one thread per process, synchronous calls
; (call, receive, reply-and-receive) with the message in registers,
; notification bits (notify, wait), and the nucleus running with
; interrupts off on a small stack per thread. A thread's stack holds its
; trap frame while it isn't running: the PC and flags the trap pushed and
; whichever registers the variant has to save.
;
; Calling conventions inside the nucleus:
;   none   no register is the nucleus's; `cur` is in memory
;   half   r14 = the current thread's TCB (bank 0 keeps it across traps);
;          r8-r12 scratch, r13 the page-fault handler's; r1-r7 belong
;          to the user unless the path says otherwise
;   full   r14 = the current TCB, r13 the page-fault handler's; everything
;          else scratch

        .include "../user/sys.inc"

CONSOLE    = 0xFFFFFF00
TIMER_PER  = 0xFFFFFF08
TIMER_ACK  = 0xFFFFFF0C

FL_I       = 0x10
FL_XL      = 0x40
PTE_V      = 1
PTE_W      = 2
PTE_X      = 4
PTE_VW     = 3
PTE_VWX    = 7
FSR_INVALID = 1
FSR_CROSS  = 0x40

NTHREADS   = 16
KSTACK     = 128            ; bytes of nucleus stack per thread
PAGE_SIZE  = 4096
SHARED_PHYS = 0x3C000       ; four pages shared by the processes that ask
DZ_LO      = 0x800000       ; demand-zero memory
DZ_HI      = 0xFF0000

; The thread control block
T_NEXT     = 0              ; link in a ready queue
T_STATE    = 4
T_CTX      = 8              ; map context
T_CTXB     = 12             ; context << 12: the map address of its page 0
T_BANK     = 16             ; register bank
T_PRIO     = 20             ; ready queue number * 4 (0 is the highest priority)
T_KSP      = 24             ; its nucleus stack pointer, at its trap frame
T_USP      = 28             ; (none) its user sp
T_HI       = 32             ; (none, half, full frames) its HI
T_FULL     = 36             ; its frame holds all its registers (an interrupt or fault)
T_PARTNER  = 40             ; who it waits for, or who it owes a reply
T_SENDQ    = 44             ; threads waiting to call it
T_SQNEXT   = 48             ; link in a send queue
T_SIGNALS  = 52
T_ID       = 56
T_PT       = 60             ; (softtlb) its page table
T_RING     = 64             ; its ring, physical; 0: none
T_MSG      = 68             ; r1-r5 for a thread woken without a hand-off (5 words)
TCB_SIZE   = 128

S_FREE     = 0
S_READY    = 1              ; running, or in a ready queue
S_RECV     = 2              ; waiting for a call
S_CALL     = 3              ; waiting for a reply from T_PARTNER
S_SEND     = 4              ; in T_PARTNER's send queue
S_WAIT     = 5              ; waiting for signals
S_DEAD     = 6

; ---------------------------------------------------------------- vectors

        .org 0x00
vectors:
        JMP  boot
        .org 0x04
        JMP  irq
        .org 0x08
        JMP  trap_illegal
        .org 0x0C
        JMP  swi
        .org 0x10
        JMP  trap_other
        .org 0x14
        JMP  trap_other
        .org 0x18
        JMP  trap_other
        .org 0x1C
        JMP  trap_other
        .org 0x20
        JMP  pagefault

        .org 0x24
tcbtab: .space 4 * NTHREADS     ; thread id -> TCB (0: none)

; ---------------------------------------------------------------- system calls

        .org 0x80
systab: .word sys_null, sys_getid, sys_yield, sys_exit, sys_putc, sys_write
        .word sys_call, sys_recv, sys_replyrecv, sys_notify, sys_wait
        .word sys_ringset, sys_ringenter, sys_mapflush

swi:    MFSR r7, fsr            ; the SWI's number (r7 is the caller's to lose)
        CMP  r7, #NSYS
        BHS  sys_bad
        LSL  r7, #2
        JMP  [systab + r7]

sys_bad:
        MOV  r1, #-1
.if full
        MTUR r1, r1
.endif
        RTI

sys_null:
.if full
        MTUR r1, r0
.else
        MOV  r1, #0
.endif
        RTI

sys_getid:
.if none
        MOV  r1, [cur]
        MOV  r1, [r1 + T_ID]
.else
        MOV  r1, [r14 + T_ID]
.endif
.if full
        MTUR r1, r1
.endif
        RTI

sys_putc:
.if full
        MFUR r1, r1
.endif
        ST   r1, byte [CONSOLE]
        RTI

; write(buffer, length): the monolithic way, copying straight from the
; caller's memory with XL on. A bad address faults into pagefault, which
; ends the thread.
sys_write:
.if full
        MFUR r1, r1
        MFUR r2, r2
.endif
        MOV  r3, r2
        BEQ  .done
        MFSR r6, flags
        MOV  r4, r6
        OR   r4, #FL_XL
        MTSR flags, r4          ; loads now go through the caller's map
.loop:  MOV  r5, byte [r1]+
        ST   r5, byte [CONSOLE]
        DEC  r3
        BNE  .loop
        MTSR flags, r6          ; XL off again
.done:  MOV  r1, r2
.if full
        MTUR r1, r1
.endif
        RTI

; ---------------------------------------------------------------- saving and switching

; Every blocking path saves the current thread with one of these, then
; ends in `switch_to` (a hand-off: the results are in registers already)
; or `schedule` (the next thread finds its results in its T_MSG).

; Switch to the thread in r6 and return to it. Its results are in
; r1-r5 (none, half: in the machine's registers; full: in its bank).
switch_to:
.if none
        ST   r6, [cur]
        MOV  sp, [r6 + T_KSP]
        MOV  r9, [r6 + T_USP]
        MTUR sp, r9
        MOV  r9, [r6 + T_CTX]
        MTSR ctx, r9
        MOV  r9, [r6 + T_FULL]
        BNE  .full
        RESTORE r8-r14
        RTI
.full:  MOV  r9, [r6 + T_HI]
        MTHI r9
        RESTORE r1-r14
        RTI
.endif
.if half
        MOV  r14, r6
        MOV  sp, [r6 + T_KSP]
        MOV  r8, [r6 + T_BANK]
        MTSR bank, r8
        MOV  r8, [r6 + T_CTX]
        MTSR ctx, r8
        MOV  r8, [r6 + T_FULL]
        BNE  .full
        RTI
.full:  MOV  r8, [r6 + T_HI]
        MTHI r8
        RESTORE r1-r7
        RTI
.endif
.if full
        MOV  r14, r6
        MOV  sp, [r6 + T_KSP]
        MOV  r8, [r6 + T_BANK]
        MTSR bank, r8
        MOV  r8, [r6 + T_CTX]
        MTSR ctx, r8
        RTI
.endif

; Run the highest-priority ready thread; with none, stop the machine.
; The thread was saved before; if its frame is partial, its results are
; in its T_MSG.
schedule:
        MOV  r7, [ready_bits]
        BEQ  idle
        CLZ  r7, r7
        LSL  r7, #2
        MOV  r6, [ready_head + r7]
        MOV  r9, [r6 + T_NEXT]
        ST   r9, [ready_head + r7]
        BNE  .left
        ST   r0, [ready_tail + r7]
        MOV  r9, [bit_for + r7]
        MOV  r8, [ready_bits]
        BIC  r8, r9
        ST   r8, [ready_bits]
.left:  MOV  r9, [r6 + T_FULL]
        BNE  switch_to
        ; a partial frame: its results from T_MSG
.if full
        MOV  r8, [r6 + T_BANK]
        MTSR bank, r8
        MOV  r8, [r6 + T_MSG]
        MTUR r1, r8
        MOV  r8, [r6 + T_MSG + 4]
        MTUR r2, r8
        MOV  r8, [r6 + T_MSG + 8]
        MTUR r3, r8
        MOV  r8, [r6 + T_MSG + 12]
        MTUR r4, r8
        MOV  r8, [r6 + T_MSG + 16]
        MTUR r5, r8
        JMP  switch_to
.else
        MOV  r1, [r6 + T_MSG]
        MOV  r2, [r6 + T_MSG + 4]
        MOV  r3, [r6 + T_MSG + 8]
        MOV  r4, [r6 + T_MSG + 12]
        MOV  r5, [r6 + T_MSG + 16]
        JMP  switch_to
.endif

; Nothing to run: every thread has ended (or waits forever).
idle:   DI
        HALT
        BRA  idle

; Put the thread in r6 at the tail of its ready queue. Uses r7-r9.
enqueue:
        MOV  r7, [r6 + T_PRIO]
        ST   r0, [r6 + T_NEXT]
        MOV  r8, [ready_tail + r7]
        BEQ  .empty
        ST   r6, [r8 + T_NEXT]
        ST   r6, [ready_tail + r7]
        RET
.empty: ST   r6, [ready_head + r7]
        ST   r6, [ready_tail + r7]
        MOV  r8, [bit_for + r7]
        MOV  r9, [ready_bits]
        OR   r9, r8
        ST   r9, [ready_bits]
        RET

; ---------------------------------------------------------------- yield and exit

sys_yield:
        MOV  r7, [ready_bits]
        BNE  .others
        RTI                     ; nobody else is ready
.others:
.if none
        SAVE r8-r14
        MOV  r8, [cur]
        ST   sp, [r8 + T_KSP]
        MFUR r9, sp
        ST   r9, [r8 + T_USP]
        ST   r0, [r8 + T_FULL]
        ST   r0, [r8 + T_MSG]
        MOV  r6, r8
.else
        ST   sp, [r14 + T_KSP]
        ST   r0, [r14 + T_FULL]
        ST   r0, [r14 + T_MSG]
        MOV  r6, r14
.endif
        BSR  enqueue
        JMP  schedule

sys_exit:
.if none
        MOV  r8, [cur]
.else
        MOV  r8, r14
.endif
        MOV  r9, #S_DEAD
        ST   r9, [r8 + T_STATE]
        MOV  r9, [n_exit]
        INC  r9
        ST   r9, [n_exit]
        JMP  schedule

; ---------------------------------------------------------------- calls, L4 style

; call(thread r1, message r2-r5): if the thread waits in recv, hand the
; message over in registers and switch to it straight away; otherwise
; queue up behind its other callers. Either way wait for the reply.
sys_call:
.if full
        MFUR r1, r1
.endif
        CMP  r1, #NTHREADS
        BHS  sys_bad
        MOV  r6, [tcbtab + r1*4]
        BEQ  sys_bad
        MOV  r7, [r6 + T_STATE]
        CMP  r7, #S_RECV
        BNE  call_queue
        ; the hand-off: save the caller
.if none
        SAVE r8-r14
        MOV  r8, [cur]
        ST   sp, [r8 + T_KSP]
        MFUR r9, sp
        ST   r9, [r8 + T_USP]
        ST   r0, [r8 + T_FULL]
.else
        MOV  r8, r14
        ST   sp, [r8 + T_KSP]
        ST   r0, [r8 + T_FULL]
.endif
        MOV  r9, #S_CALL
        ST   r9, [r8 + T_STATE]
        ST   r6, [r8 + T_PARTNER]
        MOV  r9, #S_READY
        ST   r9, [r6 + T_STATE]
        ST   r8, [r6 + T_PARTNER]   ; it owes us the reply
.if full
        ; the message moves from our bank to its bank
        MFUR r2, r2
        MFUR r3, r3
        MFUR r4, r4
        MFUR r5, r5
        MOV  r9, [r6 + T_BANK]
        MTSR bank, r9
        MOV  r9, [r8 + T_ID]
        MTUR r1, r9
        MTUR r2, r2
        MTUR r3, r3
        MTUR r4, r4
        MTUR r5, r5
.else
        MOV  r1, [r8 + T_ID]        ; the receiver learns who called
.endif
        JMP  switch_to

; The callee isn't waiting: keep the message and join its send queue.
call_queue:
.if full
        MFUR r2, r2
        MFUR r3, r3
        MFUR r4, r4
        MFUR r5, r5
.endif
.if none
        SAVE r8-r14
        MOV  r8, [cur]
        ST   sp, [r8 + T_KSP]
        MFUR r9, sp
        ST   r9, [r8 + T_USP]
.else
        MOV  r8, r14
        ST   sp, [r8 + T_KSP]
.endif
        ST   r0, [r8 + T_FULL]
        ST   r2, [r8 + T_MSG + 4]
        ST   r3, [r8 + T_MSG + 8]
        ST   r4, [r8 + T_MSG + 12]
        ST   r5, [r8 + T_MSG + 16]
        MOV  r9, #S_SEND
        ST   r9, [r8 + T_STATE]
        ST   r6, [r8 + T_PARTNER]
        ; append to r6's send queue
        ST   r0, [r8 + T_SQNEXT]
        LEA  r7, [r6 + T_SENDQ]
.walk:  MOV  r9, [r7]
        BEQ  .end
        LEA  r7, [r9 + T_SQNEXT]
        BRA  .walk
.end:   ST   r8, [r7]
        JMP  schedule

; recv(): wait for a call. reply_recv(r2-r5): reply to the thread we owe
; a reply, then the same. The reply is a hand-off back to the caller when
; nobody else is queued, which is the common case of a server and its
; client.
sys_replyrecv:
.if none
        MOV  r7, [cur]
.else
        MOV  r7, r14
.endif
        MOV  r6, [r7 + T_PARTNER]   ; the caller we owe
        BEQ  sys_recv
        ST   r0, [r7 + T_PARTNER]
        MOV  r9, [r7 + T_SENDQ]
        BNE  .busy
        ; hand-off back to the caller, and wait in recv
.if none
        SAVE r8-r14
        MOV  r8, [cur]
        ST   sp, [r8 + T_KSP]
        MFUR r9, sp
        ST   r9, [r8 + T_USP]
.else
        MOV  r8, r14
        ST   sp, [r8 + T_KSP]
.endif
        ST   r0, [r8 + T_FULL]
        MOV  r9, #S_RECV
        ST   r9, [r8 + T_STATE]
        MOV  r9, #S_READY
        ST   r9, [r6 + T_STATE]
.if full
        MFUR r2, r2
        MFUR r3, r3
        MFUR r4, r4
        MFUR r5, r5
        MOV  r9, [r6 + T_BANK]
        MTSR bank, r9
        MTUR r1, r0
        MTUR r2, r2
        MTUR r3, r3
        MTUR r4, r4
        MTUR r5, r5
.else
        MOV  r1, #0
.endif
        JMP  switch_to
.busy:  ; others are waiting to call us: the caller gets its reply later
.if full
        MFUR r2, r2
        MFUR r3, r3
        MFUR r4, r4
        MFUR r5, r5
.endif
        ST   r0, [r6 + T_MSG]
        ST   r2, [r6 + T_MSG + 4]
        ST   r3, [r6 + T_MSG + 8]
        ST   r4, [r6 + T_MSG + 12]
        ST   r5, [r6 + T_MSG + 16]
        MOV  r9, #S_READY
        ST   r9, [r6 + T_STATE]
.if none
        SAVE r8-r9              ; enqueue uses them; they are the caller's
        BSR  enqueue
        RESTORE r8-r9
.else
        BSR  enqueue
.endif
        ; fall into recv, which takes the first caller in the queue

sys_recv:
.if none
        MOV  r7, [cur]
.else
        MOV  r7, r14
.endif
        MOV  r6, [r7 + T_SENDQ]
        BEQ  .wait
        ; a caller is queued: take its message and go on running
        MOV  r9, [r6 + T_SQNEXT]
        ST   r9, [r7 + T_SENDQ]
        MOV  r9, #S_CALL
        ST   r9, [r6 + T_STATE]
        ST   r6, [r7 + T_PARTNER]
.if full
        MOV  r9, [r6 + T_ID]
        MTUR r1, r9
        MOV  r9, [r6 + T_MSG + 4]
        MTUR r2, r9
        MOV  r9, [r6 + T_MSG + 8]
        MTUR r3, r9
        MOV  r9, [r6 + T_MSG + 12]
        MTUR r4, r9
        MOV  r9, [r6 + T_MSG + 16]
        MTUR r5, r9
.else
        MOV  r1, [r6 + T_ID]
        MOV  r2, [r6 + T_MSG + 4]
        MOV  r3, [r6 + T_MSG + 8]
        MOV  r4, [r6 + T_MSG + 12]
        MOV  r5, [r6 + T_MSG + 16]
.endif
        RTI
.wait:
.if none
        SAVE r8-r14
        MOV  r8, [cur]
        ST   sp, [r8 + T_KSP]
        MFUR r9, sp
        ST   r9, [r8 + T_USP]
.else
        MOV  r8, r14
        ST   sp, [r8 + T_KSP]
.endif
        ST   r0, [r8 + T_FULL]
        MOV  r9, #S_RECV
        ST   r9, [r8 + T_STATE]
        JMP  schedule

; ---------------------------------------------------------------- notifications

; notify(thread r1, bits r2): set the bits; wake the thread if it waits.
; The caller goes on running (the woken thread queues up).
sys_notify:
.if full
        MFUR r1, r1
        MFUR r2, r2
.endif
        CMP  r1, #NTHREADS
        BHS  sys_bad
        MOV  r6, [tcbtab + r1*4]
        BEQ  sys_bad
        MOV  r7, [r6 + T_SIGNALS]
        OR   r7, r2
        MOV  r3, [r6 + T_STATE]
        CMP  r3, #S_WAIT
        BEQ  .wake
        ST   r7, [r6 + T_SIGNALS]
        RTI
.wake:  ST   r0, [r6 + T_SIGNALS]
        ST   r7, [r6 + T_MSG]
        MOV  r3, #S_READY
        ST   r3, [r6 + T_STATE]
.if none
        SAVE r8-r9
        BSR  enqueue
        RESTORE r8-r9
.else
        BSR  enqueue
.endif
        RTI

; wait(): the signals, waiting for some if there are none.
sys_wait:
.if none
        MOV  r7, [cur]
.else
        MOV  r7, r14
.endif
        MOV  r1, [r7 + T_SIGNALS]
        BEQ  .block
        ST   r0, [r7 + T_SIGNALS]
.if full
        MTUR r1, r1
.endif
        RTI
.block:
.if none
        SAVE r8-r14
        MOV  r8, [cur]
        ST   sp, [r8 + T_KSP]
        MFUR r9, sp
        ST   r9, [r8 + T_USP]
.else
        MOV  r8, r14
        ST   sp, [r8 + T_KSP]
.endif
        ST   r0, [r8 + T_FULL]
        MOV  r9, #S_WAIT
        ST   r9, [r8 + T_STATE]
        JMP  schedule

; ---------------------------------------------------------------- the ring

; ringset(address): this thread's ring is the page at that (user) address.
; The nucleus keeps its physical address (supervisor mode is untranslated)
; and reads the map once, here.
sys_ringset:
.if full
        MFUR r1, r1
.endif
.if none
        MOV  r7, [cur]
.else
        MOV  r7, r14
.endif
        MOV  r2, r1
        LSR  r2, #12
        ADD  r2, [r7 + T_CTXB]
        MTSR mapa, r2
        MFSR r3, mapd
        MOV  r4, #PTE_VW
        AND  r4, r3
        CMP  r4, #PTE_VW
        BNE  sys_bad
        MOV  r4, #-4096
        AND  r3, r4
        ST   r3, [r7 + T_RING]
.if full
        MTUR r1, r0
.else
        MOV  r1, #0
.endif
        RTI

; ringenter(): run every request in the ring, post a completion for each.
; Returns how many ran. The ring is read and written physically; buffers
; the requests name are user addresses, read with XL on.
sys_ringenter:
.if none
        MOV  r7, [cur]
        SAVE r8-r12             ; the loop needs registers
.else
        MOV  r7, r14
.endif
        MOV  r8, [r7 + T_RING]
        BEQ  .none
        MOV  r9, [r8 + RING_SQHEAD]
        MOV  r10, [r8 + RING_CQTAIL]
        MOV  r12, #0            ; how many
.next:  CMP  r9, [r8 + RING_SQTAIL]
        BEQ  .done
        MOV  r11, r9
        AND  r11, #RING_MASK
        LSL  r11, #4
        ADD  r11, r8            ; the request
        MOV  r1, [r11 + RING_SQ]
        CMP  r1, #3
        BHS  .badop
        LSL  r1, #2
        JMP  [.ops + r1]
        .align 4
.ops:   .word .nop, .putc, .write
.nop:   MOV  r2, #0
        BRA  .post
.putc:  MOV  r2, [r11 + RING_SQ + 4]
        ST   r2, byte [CONSOLE]
        MOV  r2, #1
        BRA  .post
.write: MOV  r3, [r11 + RING_SQ + 4]
        MOV  r4, [r11 + RING_SQ + 8]
        MOV  r2, r4
        BEQ  .post
        MFSR r6, flags
        MOV  r5, r6
        OR   r5, #FL_XL
        MTSR flags, r5
.copy:  MOV  r5, byte [r3]+
        ST   r5, byte [CONSOLE]
        DEC  r4
        BNE  .copy
        MTSR flags, r6
        BRA  .post
.badop: MOV  r2, #-1
.post:  MOV  r3, r10
        AND  r3, #RING_MASK
        LSL  r3, #3
        ADD  r3, r8
        MOV  r4, [r11 + RING_SQ + 12]
        ST   r4, [r3 + RING_CQ]
        ST   r2, [r3 + RING_CQ + 4]
        INC  r10
        INC  r9
        INC  r12
        BRA  .next
.done:  ST   r9, [r8 + RING_SQHEAD]
        ST   r10, [r8 + RING_CQTAIL]
        MOV  r1, r12
.if none
        RESTORE r8-r12
.endif
.if full
        MTUR r1, r1
.endif
        RTI
.none:
.if none
        RESTORE r8-r12
.endif
        JMP  sys_bad

; ---------------------------------------------------------------- the timer

; A tick preempts the running thread: save all of it, queue it at the
; back, run the first of the highest priority. If a thread is the
; interrupt's driver, it gets signal bit 0, as from notify: a user-level
; driver waits for its interrupts with wait().
irq:
.if none
        SAVE r1-r14
        MOV  r8, [cur]
        ST   sp, [r8 + T_KSP]
        MFUR r9, sp
        ST   r9, [r8 + T_USP]
        MFHI r9
        ST   r9, [r8 + T_HI]
        MOV  r9, #1
        ST   r9, [r8 + T_FULL]
        MOV  r6, r8
.endif
.if half
        SAVE r1-r7
        ST   sp, [r14 + T_KSP]
        MFHI r8
        ST   r8, [r14 + T_HI]
        MOV  r8, #1
        ST   r8, [r14 + T_FULL]
        MOV  r6, r14
.endif
.if full
        ST   sp, [r14 + T_KSP]
        MOV  r8, #1
        ST   r8, [r14 + T_FULL]
        MOV  r6, r14
.endif
        ST   r0, [TIMER_ACK]
        BSR  enqueue
        ; a user-level driver for the interrupt: signal it (bit 0)
        MOV  r6, [irq_thread]
        BEQ  schedule
        MOV  r7, [r6 + T_SIGNALS]
        OR   r7, #1
        MOV  r8, [r6 + T_STATE]
        CMP  r8, #S_WAIT
        BEQ  .wake
        ST   r7, [r6 + T_SIGNALS]
        JMP  schedule
.wake:  ST   r0, [r6 + T_SIGNALS]
        ST   r7, [r6 + T_MSG]
        MOV  r8, #S_READY
        ST   r8, [r6 + T_STATE]
        BSR  enqueue
        JMP  schedule

; ---------------------------------------------------------------- page faults

; A fault in user mode, or in the nucleus while it reads or writes user
; memory (XL/XS). Demand-zero memory gets a fresh page; with softtlb, a
; page the process's page table has is copied into the map. Anything else
; ends the thread.
;
; none saves r1-r6, whatever was running. half and full use the
; nucleus's own r8-r12 (and r13, which only this handler uses); they need
; saving only when the nucleus was running (a fault on a user access with
; XL or XS on), which the S bit of the flags in the trap frame tells.
pagefault:
.if none
        SAVE r1-r6
        MFSR r1, fsr
        MFSR r2, far
        MOV  r3, [cur]
.if softtlb
        ; the refill: is the page in the process's page table?
        MOV  r4, r2
        LSR  r4, #10
        AND  r4, #-4
        ADD  r4, [r3 + T_PT]
        MOV  r5, [r4]
        BEQ  .notmapped
        MOV  r6, r2
        LSR  r6, #12
        ADD  r6, [r3 + T_CTXB]
        MTSR mapa, r6
        MTSR mapd, r5
        RESTORE r1-r6
        RTI
.notmapped:
.endif
        MOV  r4, #FSR_INVALID
        AND  r4, r1
        BEQ  segv
        CMP  r2, #DZ_LO
        BLO  segv
        CMP  r2, #DZ_HI
        BHS  segv
        ; a fresh page, zeroed
        MOV  r4, [free_list]
        BEQ  segv
        MOV  r5, [r4]
        ST   r5, [free_list]
        MOV  r5, r4
        BSR  zero_page
        ; into the map (and the page table)
        MOV  r5, r2
        LSR  r5, #12
.if softtlb
        MOV  r6, r5
        LSL  r6, #2
        ADD  r6, [r3 + T_PT]
.endif
        ADD  r5, [r3 + T_CTXB]
        MTSR mapa, r5
        OR   r4, #PTE_VW
        MTSR mapd, r4
.if softtlb
        ST   r4, [r6]
.endif
        RESTORE r1-r6
        RTI
.else
        MOV  r13, [sp]          ; the flags when it faulted
        AND  r13, #0x20         ; S: the nucleus, with XL or XS
        BEQ  .user
        SAVE r8-r12
.user:  MFSR r8, fsr
        MFSR r9, far
.if softtlb
        MOV  r11, r9
        LSR  r11, #10
        AND  r11, #-4
        ADD  r11, [r14 + T_PT]
        MOV  r12, [r11]
        BEQ  .notmapped
        MOV  r11, r9
        LSR  r11, #12
        ADD  r11, [r14 + T_CTXB]
        MTSR mapa, r11
        MTSR mapd, r12
        BRA  .ret
.notmapped:
.endif
        MOV  r11, #FSR_INVALID
        AND  r11, r8
        BEQ  segv
        CMP  r9, #DZ_LO
        BLO  segv
        CMP  r9, #DZ_HI
        BHS  segv
        MOV  r11, [free_list]
        BEQ  segv
        MOV  r12, [r11]
        ST   r12, [free_list]
        PUSH r6                 ; zero_page uses r5 and r6
        PUSH r5
        MOV  r5, r11
        BSR  zero_page
        POP  r5
        POP  r6
        MOV  r12, r9
        LSR  r12, #12
.if softtlb
        MOV  r8, r12
        LSL  r8, #2
        ADD  r8, [r14 + T_PT]
.endif
        ADD  r12, [r14 + T_CTXB]
        MTSR mapa, r12
        OR   r11, #PTE_VW
        MTSR mapd, r11
.if softtlb
        ST   r11, [r8]
.endif
.ret:   CMP  r13, #0
        BEQ  .rti
        RESTORE r8-r12
.rti:   RTI
.endif

; Zero the page at r5 (physical). Uses r5, r6.
zero_page:
        MOV  r6, r5
        ADD  r6, #PAGE_SIZE
.z:     ST   r0, [r5]+
        ST   r0, [r5]+
        ST   r0, [r5]+
        ST   r0, [r5]+
        ST   r0, [r5]+
        ST   r0, [r5]+
        ST   r0, [r5]+
        ST   r0, [r5]+
        CMP  r5, r6
        BNE  .z
        RET

; A fault that isn't demand-zero memory: the thread ends.
segv:
        MOV  r1, #'!'
        ST   r1, byte [CONSOLE]
        MOV  r1, [n_segv]
        INC  r1
        ST   r1, [n_segv]
        ; the nucleus's own stack may hold a half-done call; reset it
.if none
        MOV  r8, [cur]
.else
        MOV  r8, r14
.endif
        MOV  r9, #S_DEAD
        ST   r9, [r8 + T_STATE]
        JMP  schedule

; mapflush() (softtlb): forget the current context's map, as if the map
; were a small cache; the page table refills it.
sys_mapflush:
.if none
        MOV  r7, [cur]
.else
        MOV  r7, r14
.endif
        MOV  r1, [r7 + T_CTXB]
        MTSR mapa, r1
        MOV  r2, #4096
.f:     MTSR mapd, r0
        DEC  r2
        BNE  .f
.if full
        MTUR r1, r0
.else
        MOV  r1, #0
.endif
        RTI

trap_illegal:
trap_other:
        MOV  r1, #'?'
        ST   r1, byte [CONSOLE]
        MOV  r1, [n_segv]
        INC  r1
        ST   r1, [n_segv]
.if none
        MOV  r8, [cur]
.else
        MOV  r8, r14
.endif
        MOV  r9, #S_DEAD
        ST   r9, [r8 + T_STATE]
        JMP  schedule

; ---------------------------------------------------------------- boot

boot:   MOV  sp, #boot_stack
.if half
        MOV  r1, #2
        MTSR sysctl, r1
.endif
.if full
        MOV  r1, #1
        MTSR sysctl, r1
.endif
        ; the page pool, as a free list
        MOV  r1, [boot_table + 8]       ; low
        MOV  r2, [boot_table + 12]      ; high
        MOV  r3, #0
.pool:  CMP  r2, r1
        BLS  .pooled
        SUB  r2, #PAGE_SIZE
        ST   r3, [r2]
        MOV  r3, r2
        BRA  .pool
.pooled:
        ST   r3, [free_list]
        ; the processes: thread i+1 runs table entry i
        MOV  r10, #0
.proc:  CMP  r10, [boot_table]
        BHS  .started
        BSR  create
        INC  r10
        BRA  .proc
.started:
        MOV  r1, [boot_table + 4]
        ST   r1, [TIMER_PER]
        JMP  schedule

; Create thread r10 + 1 from boot table entry r10.
create:
        MOV  r11, r10
        LSL  r11, #5
        ADD  r11, #boot_table + 16      ; the entry
        MOV  r12, r10
        INC  r12                        ; the thread id, context and bank
        MOV  r13, r12
        LSL  r13, #7
        ADD  r13, #tcbs                 ; its TCB (TCB_SIZE = 128)
        ST   r13, [tcbtab + r12*4]
        ST   r12, [r13 + T_ID]
        ST   r12, [r13 + T_CTX]
        ST   r12, [r13 + T_BANK]
        MOV  r1, r12
        LSL  r1, #12
        ST   r1, [r13 + T_CTXB]
        MOV  r1, [r11 + 16]
        ST   r1, [r13 + T_PRIO]
        MOV  r1, #S_READY
        ST   r1, [r13 + T_STATE]
.if softtlb
        ; a page table: four zeroed pages, contiguous (taken from the pool
        ; while it is still in address order)
        MOV  r5, [free_list]
        ST   r5, [r13 + T_PT]
        MOV  r1, #4
.pt:    MOV  r6, [r5]
        ST   r6, [free_list]
        PUSH r1
        BSR  zero_page
        POP  r1
        MOV  r5, [free_list]
        DEC  r1
        BNE  .pt
.endif
        ; its program's pages, at virtual 0
        MOV  r1, r12
        LSL  r1, #12
        MTSR mapa, r1
        MOV  r2, [r11]                  ; physical base
        MOV  r3, [r11 + 4]              ; pages
        MOV  r4, r2
        OR   r4, #PTE_VWX
.if softtlb
        MOV  r6, [r13 + T_PT]
.endif
.map:   MTSR mapd, r4
.if softtlb
        ST   r4, [r6]+
.endif
        ADD  r4, #PAGE_SIZE
        DEC  r3
        BNE  .map
        ; the shared pages
        MOV  r5, [r11 + 20]             ; flags
        MOV  r6, #2
        AND  r6, r5
        BEQ  .noshared
        MOV  r1, r12
        LSL  r1, #12
        ADD  r1, #SHARED >> 12
        MTSR mapa, r1
        MOV  r4, #SHARED_PHYS + PTE_VW
        MOV  r3, #4
.sh:    MTSR mapd, r4
        ADD  r4, #PAGE_SIZE
        DEC  r3
        BNE  .sh
.if softtlb
        ; and in the page table
        MOV  r6, [r13 + T_PT]
        ADD  r6, #(SHARED >> 12) * 4
        MOV  r4, #SHARED_PHYS + PTE_VW
        MOV  r3, #4
.shp:   ST   r4, [r6]+
        ADD  r4, #PAGE_SIZE
        DEC  r3
        BNE  .shp
.endif
.noshared:
        ; the I/O page, for a user-level driver
        MOV  r6, #1
        AND  r6, r5
        BEQ  .noio
        MOV  r1, r12
        LSL  r1, #12
        ADD  r1, #IOPAGE >> 12
        MTSR mapa, r1
        MOV  r4, #0xFFFFF000 + PTE_VW
        MTSR mapd, r4
.if softtlb
        MOV  r6, [r13 + T_PT]
        ST   r4, [r6 + (IOPAGE >> 12) * 4]
.endif
.noio:
        ; the interrupt's driver
        MOV  r6, #4
        AND  r6, r5
        BEQ  .noirq
        ST   r13, [irq_thread]
.noirq:
        ; its stack in the nucleus, with a trap frame to start from
        MOV  r6, r12
        INC  r6
        LSL  r6, #7                     ; KSTACK = 128
        ADD  r6, #kstacks               ; the top
        MOV  r1, [r11 + 8]              ; entry
        ST   r1, -[r6]
        MOV  r1, #FL_I                  ; user mode, interrupts on
        ST   r1, -[r6]
        MOV  r2, [r11 + 12]             ; the arguments, for r1
        MOV  r3, [r11 + 24]             ; and r2
.if none
        MOV  r4, #12
.z:     ST   r0, -[r6]
        DEC  r4
        BNE  .z
        ST   r3, -[r6]                  ; r2
        ST   r2, -[r6]                  ; r1
        MOV  r1, #STACK_TOP
        ST   r1, [r13 + T_USP]
        MOV  r1, #1
        ST   r1, [r13 + T_FULL]
.endif
.if half
        MOV  r4, #5
.z:     ST   r0, -[r6]
        DEC  r4
        BNE  .z
        ST   r3, -[r6]                  ; r2
        ST   r2, -[r6]                  ; r1
        MTSR bank, r12
        MOV  r1, #STACK_TOP
        MTUR sp, r1
        MOV  r1, #1
        ST   r1, [r13 + T_FULL]
.endif
.if full
        MTSR bank, r12
        MTUR r1, r2
        MTUR r2, r3
        MOV  r1, #STACK_TOP
        MTUR sp, r1
        MOV  r1, #1
        ST   r1, [r13 + T_FULL]
.endif
        ST   r6, [r13 + T_KSP]
        MOV  r6, r13
        BSR  enqueue
        RET

; ---------------------------------------------------------------- data

        .align 4
.if none
cur:    .word 0
.endif
ready_bits: .word 0
ready_head: .space 4 * 32
ready_tail: .space 4 * 32
bit_for:
        .word 0x80000000, 0x40000000, 0x20000000, 0x10000000
        .word 0x08000000, 0x04000000, 0x02000000, 0x01000000
        .word 0x00800000, 0x00400000, 0x00200000, 0x00100000
        .word 0x00080000, 0x00040000, 0x00020000, 0x00010000
        .word 0x00008000, 0x00004000, 0x00002000, 0x00001000
        .word 0x00000800, 0x00000400, 0x00000200, 0x00000100
        .word 0x00000080, 0x00000040, 0x00000020, 0x00000010
        .word 0x00000008, 0x00000004, 0x00000002, 0x00000001
free_list:  .word 0
irq_thread: .word 0             ; the thread the timer's interrupts go to, if any
n_exit:     .word 0
n_segv:     .word 0

; Filled in by build.py: count, timer period, page pool low and high,
; then per process: physical base, pages, entry, argument (r1), priority
; * 4, flags (1: the I/O page, 2: the shared pages, 4: it is the timer
; interrupt's driver), a second argument (r2), a spare word.
boot_table: .space 16 + 32 * 12
boot_table_end:

        .space 128
boot_stack:
        .align 4
tcbs:   .space TCB_SIZE * NTHREADS
kstacks: .space KSTACK * (NTHREADS + 1)
