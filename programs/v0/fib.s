; fib: recursive fib(18) (counting the calls), then fib(0..46) iteratively
; in 32 bits.

        .include "lib/start.s"

main:   PUSH r8
        PUSH r9
        PUSH r10
        PUSH r11
        PUSH r12

        ; ---- recursive ----
        MVI  r1, 18
        BSR  fib
        MOV  r8, r1
        LI   r1, #s_rec
        CALL puts
        MOV  r1, r8
        CALL print_u16
        LI   r1, #s_calls
        CALL puts
        LD   r1, [calls]
        CALL print_u16
        LI   r1, #s_calls2
        CALL puts

        ; ---- iterative, 32 bits ----
        ; Two terms per pass: print a, a += b, print b, b += a. Alternating
        ; the roles saves the register shuffle of "a, b = b, a + b", which a
        ; two-operand ADD would otherwise need four MOVs for.
        MVI  r8, 0              ; r9:r8 = a = fib(n)
        MVI  r9, 0
        MVI  r10, 1             ; r11:r10 = b = fib(n + 1)
        MVI  r11, 0
        MVI  r12, 0             ; r12 = n
.loop:  MOV  r1, r12
        MOV  r2, r8
        MOV  r3, r9
        BSR  line
        ADD  r8, r10            ; a = fib(n + 2)
        ADC  r9, r11
        INC  r12
        CMPI r12, 47
        BEQ  .done
        MOV  r1, r12
        MOV  r2, r10
        MOV  r3, r11
        BSR  line
        ADD  r10, r8            ; b = fib(n + 3)
        ADC  r11, r9
        INC  r12
        BRA  .loop
.done:
        POP  r12
        POP  r11
        POP  r10
        POP  r9
        POP  r8
        RET

; line: print "fib(r1) = r3:r2".
line:   PUSH r2
        PUSH r3
        PUSH r1
        LI   r1, #s_fib
        CALL puts
        POP  r1
        CALL print_u16
        LI   r1, #s_eq
        CALL puts
        POP  r2
        POP  r1
        CALL print_u32
        JMP  newline

; fib: r1 = n -> r1 = fib(n), the slow recursive way.
fib:    LD   r2, [calls]
        INC  r2
        ST   r2, [calls]
        CMPI r1, 2
        BLO  .done              ; fib(0) = 0, fib(1) = 1
        PUSH r8
        PUSH r9
        MOV  r8, r1
        DEC  r1
        BSR  fib
        MOV  r9, r1             ; fib(n - 1)
        MOV  r1, r8
        ADDI r1, -2
        BSR  fib
        ADD  r1, r9
        POP  r9
        POP  r8
.done:  RET

calls:  .word 0
s_rec:  .asciz "recursive fib(18) = "
s_calls: .asciz " ("
s_calls2: .asciz " calls)\n"
s_fib:  .asciz "fib("
s_eq:   .asciz ") = "

        .include "lib/console.s"
        .include "lib/print.s"
