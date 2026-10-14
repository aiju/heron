; Hello, three ways: putc, write, and a stack in demand-zero memory.
        .include "sys.inc"
        .org 0
start:  SWI  #SYS_GETID
        ADD  r1, #'0'
        SWI  #SYS_PUTC
        MOV  r1, #':'
        SWI  #SYS_PUTC
        LEA  r1, [msg]
        MOV  r2, #msg_end - msg
        SWI  #SYS_WRITE
        ; use the stack (demand-zero pages)
        BSR  sub
        SWI  #SYS_EXIT
sub:    PUSH r8
        MOV  r8, #'.'
        MOV  r1, r8
        SWI  #SYS_PUTC
        MOV  r1, #10
        SWI  #SYS_PUTC
        POP  r8
        RET
msg:    .ascii " hello"
msg_end:
