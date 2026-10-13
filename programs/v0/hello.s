; hello: the smallest complete program.

        .include "lib/start.s"

main:   LI   r1, #msg
.loop:  LDB  r2, [r1]           ; loads set Z, so no compare needed
        BEQ  .done
        STB  r2, [0xFF00]       ; console out
        ADDI r1, 1
        BRA  .loop
.done:  RET

msg:    .asciz "Hello, world!\n"
