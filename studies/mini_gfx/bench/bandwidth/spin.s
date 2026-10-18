; spin(n): n taken branches in a tight loop: every decode after a jump
; fetches its parcel on demand, the longest cycles there are
        .global _spin
        .section .text._spin
_spin:  BRA  .a
.a:     BRA  .b
.b:     BRA  .c
.c:     DEC  r1
        BNE  .a
        RET
