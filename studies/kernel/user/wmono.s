; The monolithic write: r1 writes of the first r2 bytes of a line, each
; one system call that copies them to the console. Then exit.
        .include "sys.inc"
        .org 0
start:  MOV  r8, r1
        MOV  r10, r2
.loop:  LEA  r1, [line]
        MOV  r2, r10
        SWI  #SYS_WRITE
        DEC  r8
        BNE  .loop
        SWI  #SYS_EXIT
        .include "line.inc"
