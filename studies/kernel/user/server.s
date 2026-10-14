; A server: receive a call, reply with its first word plus one, forever.
        .include "sys.inc"
        .org 0
start:  SWI  #SYS_RECV
.loop:  INC  r2
        SWI  #SYS_REPLYRECV
        BRA  .loop
