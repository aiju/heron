; hello: print "Hello, world!" -- the smallest complete program, using puts
; from the console library.

        .include "lib/start.s"

main:   LEA  r1, [msg]          ; address of the string
        BRA  puts               ; tail call: puts returns straight to main's caller

msg:    .asciz "Hello, world!\n"
        .align 2

        .include "lib/console.s"
