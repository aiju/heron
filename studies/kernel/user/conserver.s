; The console server: a user-level driver with the I/O page mapped. Each
; call is (r2: address in the shared pages, r3: length); it copies the
; bytes to the console and replies with the length.
        .include "sys.inc"
        .org 0
start:  MOV  r12, #UCONSOLE
        SWI  #SYS_RECV
.loop:  MOV  r6, r3
        BEQ  .done
.copy:  MOV  r4, byte [r2]+
        ST   r4, byte [r12]
        DEC  r6
        BNE  .copy
.done:  MOV  r2, r3
        SWI  #SYS_REPLYRECV
        BRA  .loop
