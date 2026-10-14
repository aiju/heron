; The null system call, r1 times; then exit.
        .include "sys.inc"
        .org 0
start:  MOV  r8, r1
.loop:  SWI  #SYS_NULL
        DEC  r8
        BNE  .loop
        SWI  #SYS_EXIT
