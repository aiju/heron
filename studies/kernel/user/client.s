; Call the server (thread 1) r1 times with a four-word message, and check
; each reply; then exit. With r2 = 0 the message stays the same.
        .include "sys.inc"
        .org 0
start:  MOV  r8, r1
        MOV  r9, #0
.loop:  MOV  r1, #1
        MOV  r2, r9
        MOV  r3, #2
        MOV  r4, #3
        MOV  r5, #4
        SWI  #SYS_CALL
        CMP  r2, r9             ; the server adds one to the first word
        BEQ  .bad
        INC  r9
        DEC  r8
        BNE  .loop
        SWI  #SYS_EXIT
.bad:   MOV  r1, #'X'
        SWI  #SYS_PUTC
        SWI  #SYS_EXIT
