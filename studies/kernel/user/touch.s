; Touch r1 pages of demand-zero memory, one store each; then exit.
        .include "sys.inc"
        .org 0
start:  MOV  r8, r1
        MOV  r9, #HEAP
.loop:  ST   r8, [r9]
        ADD  r9, #4096
        DEC  r8
        BNE  .loop
        SWI  #SYS_EXIT
