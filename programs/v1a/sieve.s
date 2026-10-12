; sieve: Sieve of Eratosthenes over a byte array, primes below 8192.
; Prints how many there are and the last ten.
;
; flags[i] = 1 means "i may be prime". Each prime i crosses off i*i, i*i + i,
; ... (smaller multiples were already crossed off by smaller primes), for
; i*i < N. The flags are 0 or 1, so counting is just adding them up.

        .include "lib/start.s"

N = 8192

main:   SAVE r8-r11

        LEA  r1, flags
        MVI  r2, 1
        LI   r3, #N
        BSR  memset
        STH  r0, [flags]        ; 0 and 1 are not primes: one store clears both

        ; ---- sieve ----
        MVI  r8, 2              ; r8 = i
        MVI  r9, 4              ; r9 = i * i, kept up to date by adding 2i + 1
        LEA  r11, flags + N     ; r11 = end of the array
.outer: LDB  r1, [flags + r8]
        BEQ  .next
        LEA  r10, [r9 + flags]  ; r10 = &flags[i * i]
.cross: STB  r0, [r10]
        ADD  r10, r8
        CMP  r10, r11
        BLO  .cross
.next:  ADD  r9, r8
        ADD  r9, r8
        ADDI r9, 1
        ADDI r8, 1
        CMP  r9, #N
        BLO  .outer

        ; ---- count, four flags per iteration: the offsets are free ----
        MVI  r9, 0
        LEA  r10, flags
.count: LDB  r1, [r10]
        ADD  r9, r1
        LDB  r1, [r10 + 1]
        ADD  r9, r1
        LDB  r1, [r10 + 2]
        ADD  r9, r1
        LDB  r1, [r10 + 3]
        ADD  r9, r1
        ADDI r10, 4
        CMP  r10, r11
        BLO  .count
        LEA  r1, s_count
        BSR  puts
        MOV  r1, r9
        BSR  print_u32
        BSR  newline

        ; ---- the last ten: scanning down, push each prime found, so the
        ; smallest of the ten ends up on top of the stack ----
        LI   r10, #N
        MVI  r9, 10
.scan:  ADDI r10, -1
        LDB  r1, [flags + r10]
        BEQ  .scan
        PUSH r10
        ADDI r9, -1
        BNE  .scan
        LEA  r1, s_last
        BSR  puts
        MVI  r9, 10
.print: BSR  space
        POP  r1
        BSR  print_u32
        ADDI r9, -1
        BNE  .print
        BSR  newline

        RESTORE r8-r11
        RET

s_count: .asciz "primes below 8192: "
s_last:  .asciz "last ten:"

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"

        .align 4
flags:  .space N
