; fib: recursive fib(18), counting the calls, then fib(0) to fib(46)
; iteratively. fib(46) = 1836311903 is the last one that fits in 31 bits, so
; plain 32-bit adds and print_u32 do.

        .include "lib/start.s"

main:   SAVE r8-r10

        ; ---- recursive ----
        MVI  r1, 18
        BSR  fib
        MOV  r8, r1
        LEA  r1, s_rec
        BSR  puts
        MOV  r1, r8
        BSR  print_u32
        LEA  r1, s_calls
        BSR  puts
        LD   r1, [calls]
        BSR  print_u32
        LEA  r1, s_calls2
        BSR  puts

        ; ---- iterative ----
        MVI  r8, 0              ; r8 = a = fib(n)
        MVI  r9, 1              ; r9 = b = fib(n + 1)
        MVI  r10, 0             ; r10 = n
.loop:  LEA  r1, s_fib          ; "fib(n) = a"
        BSR  puts
        MOV  r1, r10
        BSR  print_u32
        LEA  r1, s_eq
        BSR  puts
        MOV  r1, r8
        BSR  print_u32
        BSR  newline
        MOV  r1, r8             ; a, b = b, a + b
        ADD  r1, r9
        MOV  r8, r9
        MOV  r9, r1
        ADDI r10, 1
        CMPI r10, 47
        BLO  .loop

        RESTORE r8-r10
        RET

; fib: r1 = n -> r1 = fib(n), the slow recursive way, counting the calls.
; Nothing needs to survive the first recursive call except n - 1, which waits
; in a stack slot; the slot then holds fib(n - 1) across the second call.
; (Cheaper than saving and restoring two callee-saved registers.)
fib:    LD   r2, [calls]
        ADDI r2, 1
        ST   r2, [calls]
        CMPI r1, 2
        BLO  .done              ; fib(0) = 0, fib(1) = 1
        ADDI r1, -1
        PUSH r1                 ; [sp] = n - 1
        BSR  fib                ; r1 = fib(n - 1)
        LD   r2, [sp]           ; swap: r1 = n - 1, [sp] = fib(n - 1)
        ST   r1, [sp]
        MOV  r1, r2
        ADDI r1, -1
        BSR  fib                ; r1 = fib(n - 2)
        POP  r2
        ADD  r1, r2             ; + fib(n - 1)
.done:  RET

s_rec:    .asciz "recursive fib(18) = "
s_calls:  .asciz " ("
s_calls2: .asciz " calls)\n"
s_fib:    .asciz "fib("
s_eq:     .asciz ") = "

        .align 4
calls:  .word 0

        .include "lib/console.s"
        .include "lib/print.s"
