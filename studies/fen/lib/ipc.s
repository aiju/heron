; The IPC system calls, whose message is r0-r7 (kernel/ipc.c). Each takes
; the message from a msg_t in memory and puts the answer back there.

        .global _ipc_call, _ipc_recv, _ipc_reply, _ipc_reply_recv

; int ipc_call(int port, msg_t *m): send *m, wait for the reply, into *m;
; the reply's word 0 (or the kernel's error)
        .section .text._ipc_call
_ipc_call:
        SAVE r7-r9
        MOV  r8, r1
        MOV  r9, r2
        LDM  r9, r0-r7
        SWI  #8
        STM  r9, r0-r7
        MOV  r1, r0
        RESTORE r7-r9
        RET

; int ipc_recv(int port, msg_t *m, int *pid): the next message or
; notification into *m; the rcvid (0 for a notification) or an error, and
; the sender's pid in *pid if pid isn't 0
        .section .text._ipc_recv
_ipc_recv:
        SAVE r7-r11
        MOV  r8, r1
        MOV  r10, r2
        MOV  r11, r3
        SWI  #9
        STM  r10, r0-r7
        CMP  r11, #0
        BEQ  .r1
        MOV  [r11], r9
.r1:    MOV  r1, r8
        RESTORE r7-r11
        RET

; int ipc_reply(int rcvid, msg_t *m)
        .section .text._ipc_reply
_ipc_reply:
        SAVE r7-r10
        MOV  r8, r1
        MOV  r10, r2
        LDM  r10, r0-r7
        SWI  #10
        MOV  r1, r8
        RESTORE r7-r10
        RET

; int ipc_reply_recv(int rcvid, msg_t *m, int port, int *pid): reply with
; *m to rcvid if it's > 0, then receive into *m, as ipc_recv
        .section .text._ipc_reply_recv
_ipc_reply_recv:
        SAVE r7-r11
        MOV  r8, r1
        MOV  r9, r3
        MOV  r10, r2
        MOV  r11, r4
        LDM  r10, r0-r7
        SWI  #11
        STM  r10, r0-r7
        CMP  r11, #0
        BEQ  .rr1
        MOV  [r11], r9
.rr1:   MOV  r1, r8
        RESTORE r7-r11
        RET
