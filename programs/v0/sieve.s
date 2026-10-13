; sieve: Sieve of Eratosthenes over a byte array, primes below 8192.
; Prints how many there are and the last ten.

        .include "lib/start.s"

N = 8192

main:   PUSH r8
        PUSH r9
        PUSH r10
        PUSH r11
        PUSH r12

        LI   r1, #flags         ; flags[i] = 1: "i may be prime"
        MVI  r2, 1
        LI   r3, #N
        CALL memset
        STB  r0, [flags]        ; 0 and 1 are not primes
        STB  r0, [flags + 1]

        MVI  r8, 2              ; r8 = i
        MVI  r9, 4              ; r9 = i * i, kept up to date by adding 2i + 1
        LI   r11, #N
.outer: LDB  r1, [flags + r8]
        BEQ  .nexti
        MOV  r10, r9            ; cross off i*i, i*i + i, ... (smaller multiples
.cross: STB  r0, [flags + r10]  ; were crossed off by smaller primes)
        ADD  r10, r8
        CMP  r10, r11
        BLO  .cross
.nexti: ADD  r9, r8
        ADD  r9, r8
        INC  r9
        INC  r8
        CMP  r9, r11
        BLO  .outer

        ; ---- count: the flags are 0 or 1, so just add them up ----
        MVI  r9, 0              ; count
        LI   r10, #flags
        LI   r11, #flags + N
.count: LDB  r1, [r10]          ; four per iteration: the offsets are free
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
        LI   r1, #s_count
        CALL puts
        MOV  r1, r9
        CALL print_u16
        CALL newline

        ; ---- the last ten, found scanning down and stored back to front ----
        LI   r10, #N - 1
        MVI  r12, 10
        LI   r8, #last10 + 20
.scan:  LDB  r1, [flags + r10]
        BEQ  .notp
        ADDI r8, -2
        ST   r10, [r8]
        DEC  r12
        BEQ  .found
.notp:  DEC  r10
        BRA  .scan
.found: LI   r1, #s_last
        CALL puts
        MVI  r12, 10            ; r8 points at the smallest of the ten
.print: CALL space
        LD   r1, [r8]
        CALL print_u16
        ADDI r8, 2
        DEC  r12
        BNE  .print
        CALL newline

        POP  r12
        POP  r11
        POP  r10
        POP  r9
        POP  r8
        RET

s_count: .asciz "primes below 8192: "
s_last:  .asciz "last ten:"
        .align 2
last10: .space 20

        .include "lib/console.s"
        .include "lib/print.s"
        .include "lib/string.s"

flags:  .space N
