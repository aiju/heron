; Count down from r1, with nothing else; then exit. Two of these, with
; the timer on, measure preemption.
        .include "sys.inc"
        .org 0
start:  MOV  r8, r1
.loop:  DEC  r8
        BNE  .loop
        SWI  #SYS_EXIT
