; Yield, r1 times; then exit. Two of these switch back and forth.
        .include "sys.inc"
        .org 0
start:  MOV  r8, r1
.loop:  SWI  #SYS_YIELD
        DEC  r8
        BNE  .loop
        SWI  #SYS_EXIT
