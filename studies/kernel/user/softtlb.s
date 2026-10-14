; For the softtlb nucleus: r1 rounds of touching r2 pages, forgetting the
; map before each round, so every round refills the map from the page
; table (one refill per page, plus this program's code and stack).
        .include "sys.inc"
        .org 0
start:  MOV  r8, r1
        MOV  r10, r2
.round: SWI  #SYS_MAPFLUSH
        MOV  r9, #HEAP
        MOV  r11, r10
.page:  MOV  r1, [r9]
        ADD  r9, #4096
        DEC  r11
        BNE  .page
        DEC  r8
        BNE  .round
        SWI  #SYS_EXIT
