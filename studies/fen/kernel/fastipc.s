; The IPC's fast path: ipc_call to a server that is waiting, and
; ipc_reply_recv to a client that is waiting with nothing else for the
; server to receive, each a direct switch from one thread to the other
; when the scheduler would choose it anyway. It does what ipc.c's
; sys_ipc_call and sys_ipc_reply_recv do in those cases, with the
; registers named and nothing called; every other case, and every error,
; goes to them (ksys.s's stubs), before anything has changed.
;
; The SWI's vector jumps here (syscalls.py's FAST). On entry the caller's
; bank is `bank`, and its trap frame is at sp: sr at [sp], PC at [sp + 4].
; The structures' offsets are kernel/offsets.c's, which the build puts in
; front of this file as .equ. Built with COPY_UR (to measure what BCOPY
; saves), each BCOPY becomes the copy through the eight free registers its
; comment names, with MFUR and MTUR.

        .far _current, _need_resched, _ready_bits
        .far ksys_ipc_call, ksys_ipc_reply_recv
        .global fast_ipc_call, fast_ipc_reply_recv

        .section .text.fastipc

; ipc_call: the port in r8, the message in r0-r7
fast_ipc_call:
        MFUR r1, r8
        CMP  r1, #K_MAX_PORTS           ; (unsigned: a negative id too)
        BHS  .slow
        LEA  r2, [r1 + r1*4]
        LEA  r2, [pc + _ports + r2*4]   ; p = &ports[id]
        MOVS r3, [r2 + PT_OWNER]
        BEQ  .slow                      ; a free port (and port 0)
        MOVS r4, [r2 + PT_RECEIVERS]
        BEQ  .slow                      ; s, the server, isn't waiting
        MOVS r5, [_ready_bits]          ; is a ready thread above s?
        BEQ  .go
        CLZ  r5, r5
        ADD  r5, [r4 + T_PRIO]
        CMP  r5, #31
        BLT  .slow
; take s off the port's receivers, where it is the head
.go:    MOV  r5, [r4 + T_NEXT]
        CMP  r5, r4
        BNE  .more
        CLR  [r2 + PT_RECEIVERS]
        BRA  .off
.more:  MOV  r6, [r4 + T_PREV]
        MOV  [r6 + T_NEXT], r5
        MOV  [r5 + T_PREV], r6
        MOV  [r2 + PT_RECEIVERS], r5
.off:   CLR  [r4 + T_NEXT]
        CLR  [r4 + T_PREV]
        CLR  [r4 + T_PORT]
; the message: the client's r0-r7 to s, and in s's r8 and r9 the rcvid
; (the client's bank and generation) and the client's pid
        MOV  r5, [_current]             ; t, the client
        MOV  r6, [r5 + T_ID]
        MOV  r7, [r4 + T_ID]
        BCOPY r7, r6                    ; COPY_UR: r0 r1 r2 r3 r8 r9 r10 r11
        MOV  r8, [r5 + T_RCVID]
        MOV  r9, [r5 + T_PROC]
        MOV  r9, [r9 + P_PID]
        MTSR bank, r7
        MTUR r8, r8
        MTUR r9, r9
; t waits for s's reply
        MOV  r0, #TS_REPLY
        MOV  [r5 + T_STATE], r0
        MOV  [r5 + T_PEER], r4
        CLR  [r5 + T_PORT]
        MOV  r10, [r4 + T_PROC]
        MOV  r0, [r10 + P_PID]
        MOV  [r5 + T_PEER_PID], r0
        MOV  r0, [sp]
        MOV  [r5 + T_SR], r0
        MOV  r0, [sp + 4]
        MOV  [r5 + T_PC], r0
        BRA  fast_switch
.slow:  JMP  ksys_ipc_call

; ipc_reply_recv: the reply in r0-r7 to rcvid r8, then a receive on the
; port in r9
fast_ipc_reply_recv:
        MFUR r1, r8                     ; the rcvid
        CMP  r1, #0
        BLE  .slow
        ZXB  r2, r1                     ; its bank
        LEA  r3, [r2 + r2*8]
        LEA  r3, [pc + _threads + r3*8] ; c = &threads[bank]
        MOV  r4, [r3 + T_STATE]
        CMP  r4, #TS_REPLY
        BNE  .slow                      ; not waiting for a reply
        CMP  r1, [r3 + T_RCVID]
        BNE  .slow                      ; a stale rcvid
        MOV  r5, [_current]             ; t, the server
        MOV  r6, [r5 + T_PROC]
        MOV  r7, [r6 + P_PID]
        CMP  r7, [r3 + T_PEER_PID]
        BNE  .slow                      ; waiting for another process
        MFUR r8, r9                     ; the port
        CMP  r8, #K_MAX_PORTS
        BHS  .slow
        LEA  r9, [r8 + r8*4]
        LEA  r9, [pc + _ports + r9*4]   ; p
        CMP  r7, [r9 + PT_OWNER]
        BNE  .slow                      ; not t's (or free)
        MOVS r0, [r9 + PT_PENDING]
        BNE  .slow                      ; a notification to take at once
        MOVS r0, [r9 + PT_SENDERS]
        BNE  .slow                      ; a caller to take at once
        MOVS r0, [_ready_bits]          ; is a ready thread above c?
        BEQ  .go
        CLZ  r0, r0
        ADD  r0, [r3 + T_PRIO]
        CMP  r0, #31
        BLT  .slow
; the reply to c
.go:    MOV  r0, [r5 + T_ID]
        BCOPY r2, r0                    ; COPY_UR: r1 r4 r6 r7 r8 r10 r11 r12
        CLR  [r3 + T_PEER]
        CLR  [r3 + T_PEER_PID]
; t waits on the port, at the end of its receivers
        MOV  [r5 + T_PORT], r9
        MOV  r0, #TS_RECV
        MOV  [r5 + T_STATE], r0
        MOVS r0, [r9 + PT_RECEIVERS]
        BNE  .append
        MOV  [r5 + T_NEXT], r5
        MOV  [r5 + T_PREV], r5
        MOV  [r9 + PT_RECEIVERS], r5
        BRA  .queued
.append:
        MOV  r11, [r0 + T_PREV]
        MOV  [r5 + T_PREV], r11
        MOV  [r5 + T_NEXT], r0
        MOV  [r11 + T_NEXT], r5
        MOV  [r0 + T_PREV], r5
.queued:
        MOV  r0, [sp]
        MOV  [r5 + T_SR], r0
        MOV  r0, [sp + 4]
        MOV  [r5 + T_PC], r0
        MTSR bank, r2
        MOV  r4, r3
        MOV  r10, [r3 + T_PROC]
        BRA  fast_switch
.slow:  JMP  ksys_ipc_reply_recv

; run r4, whose bank `bank` already is, instead of r5, which has blocked
; with its frame saved; r10 is r4's process (proc.c's switch_to)
fast_switch:
        MOV  r0, #TS_RUNNING
        MOV  [r4 + T_STATE], r0
        MOVS r0, [r4 + T_SLICE]
        BGT  .slice
        MOV  r0, #K_SLICE_TICKS
        MOV  [r4 + T_SLICE], r0
.slice: MOV  [_current], r4
        CLR  [_need_resched]
        MOV  r0, [r4 + T_SR]
        MOV  [sp], r0
        MOV  r0, [r4 + T_PC]
        MOV  [sp + 4], r0
        CMP  r10, [r5 + T_PROC]
        BEQ  .same
        MOV  r0, [r10 + P_PID]
        MTSR ctx, r0
.same:  RTI
